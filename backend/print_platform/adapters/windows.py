"""Only this module knows Win32. It never decides authorization or history semantics."""

import ctypes
from contextlib import contextmanager


class WindowsPrinter:
    def __init__(self, queue, cancel_verified=False):
        import win32print

        self.queue, self.cancel_verified, self.spool = queue, cancel_verified, win32print

    @contextmanager
    def handle(self):
        handle = self.spool.OpenPrinter(self.queue)
        try:
            yield handle
        finally:
            self.spool.ClosePrinter(handle)

    @contextmanager
    def dc(self, orientation):
        import win32gui
        import win32ui

        with self.handle() as printer:
            mode = self.spool.GetPrinter(printer, 2)["pDevMode"]
            mode.PaperSize, mode.Orientation, mode.Copies, mode.Duplex = (
                9,
                2 if orientation == "landscape" else 1,
                1,
                1,
            )
            mode.Fields |= 0x2 | 0x1 | 0x100 | 0x1000
            result = self.spool.DocumentProperties(0, printer, self.queue, mode, mode, 10)
            if result != 1:
                raise RuntimeError("驱动拒绝打印参数")
            handle = win32gui.CreateDC("WINSPOOL", self.queue, mode)
            context = win32ui.CreateDCFromHandle(handle)
            try:
                yield context
            finally:
                context.DeleteDC()

    def capabilities(self, orientation="portrait"):
        with self.dc(orientation) as dc:
            xdpi, ydpi = dc.GetDeviceCaps(88), dc.GetDeviceCaps(90)
            values = {
                "width_mm": dc.GetDeviceCaps(110) * 25.4 / xdpi,
                "height_mm": dc.GetDeviceCaps(111) * 25.4 / ydpi,
                "printable_width_mm": dc.GetDeviceCaps(8) * 25.4 / xdpi,
                "printable_height_mm": dc.GetDeviceCaps(10) * 25.4 / ydpi,
                "left_mm": dc.GetDeviceCaps(112) * 25.4 / xdpi,
                "top_mm": dc.GetDeviceCaps(113) * 25.4 / ydpi,
            }
            values = {key: round(value, 4) for key, value in values.items()}
            return {
                "cancel_supported": self.cancel_verified,
                "geometry": {"version": "win32-devicecaps-v1", "source": "device", **values},
            }

    def device_status(self):
        with self.handle() as handle:
            info = self.spool.GetPrinter(handle, 2)
        status = info["Status"]
        reasons = []
        for flag, message in [
            (0x1, "设备队列已暂停"),
            (0x2, "设备错误"),
            (0x8, "卡纸"),
            (0x10, "缺纸"),
            (0x40, "纸张异常"),
            (0x80, "离线"),
            (0x1000, "设备不可用"),
            (0x100000, "碳粉耗尽"),
            (0x400000, "需要现场处理"),
        ]:
            if status & flag:
                reasons.append(message)
        return {
            "available": True,
            "blocked": bool(reasons),
            "message": "、".join(reasons) or "设备可用",
            "raw_status": status,
            "toner": "low" if status & 0x20000 else "unknown",
        }

    def jobs(self):
        with self.handle() as handle:
            return self.spool.EnumJobs(handle, 0, 10000, 1)

    def reference(self, job):
        return {
            "backend": "windows",
            "queue": self.queue,
            "job_id": str(job["JobId"]),
            "document_marker": job["pDocument"],
        }

    def find_job(self, marker):
        for job in self.jobs():
            if job["pDocument"] == marker:
                return self.reference(job)
        return None

    def query_job(self, reference):
        if reference["queue"] != self.queue:
            raise RuntimeError("任务队列配置已变化，需人工对账")
        jobs = self.jobs()  # Failure propagates; never treat query failure as disappearance.
        for job in jobs:
            if str(job["JobId"]) == reference["job_id"] and job["pDocument"] == reference["document_marker"]:
                return {"present": True, "raw_status": job["Status"]}
        return {"present": False}

    def cancel_job(self, reference):
        if not self.cancel_verified:
            raise RuntimeError("在印取消未验收")
        if not self.query_job(reference)["present"]:
            return False
        with self.handle() as handle:
            self.spool.SetJob(handle, int(reference["job_id"]), 0, None, self.spool.JOB_CONTROL_DELETE)
        return True

    def submit(self, pdf, copies, orientation, marker, on_job):
        import pypdfium2 as pdfium
        from PIL import ImageWin

        class DocInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_int),
                ("lpszDocName", ctypes.c_wchar_p),
                ("lpszOutput", ctypes.c_wchar_p),
                ("lpszDatatype", ctypes.c_wchar_p),
                ("fwType", ctypes.c_uint32),
            ]

        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi.StartDocW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DocInfo)]
        gdi.StartDocW.restype = ctypes.c_int
        gdi.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdi.SetStretchBltMode.restype = ctypes.c_int
        gdi.SetBrushOrgEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        gdi.SetBrushOrgEx.restype = ctypes.c_int
        with self.dc(orientation) as dc:
            info = DocInfo(ctypes.sizeof(DocInfo), marker, None, None, 0)
            job_id = gdi.StartDocW(dc.GetHandleOutput(), ctypes.byref(info))
            if job_id <= 0:
                raise RuntimeError("StartDocW 未获得作业 ID")
            reference = {
                "backend": "windows",
                "queue": self.queue,
                "job_id": str(job_id),
                "document_marker": marker,
            }
            try:
                on_job(reference)  # Persist immediately, before page rendering or EndDoc.
                document = pdfium.PdfDocument(str(pdf))
                try:
                    for _ in range(copies):
                        for index in range(len(document)):
                            page = document[index]
                            bitmap = page.render(scale=300 / 72)
                            image = bitmap.to_pil().convert("RGB")
                            try:
                                dc.StartPage()
                                hdc = dc.GetHandleOutput()
                                if not gdi.SetStretchBltMode(hdc, 4):  # HALFTONE
                                    raise ctypes.WinError(ctypes.get_last_error())
                                if not gdi.SetBrushOrgEx(hdc, 0, 0, None):
                                    raise ctypes.WinError(ctypes.get_last_error())
                                left, top = dc.GetDeviceCaps(112), dc.GetDeviceCaps(113)
                                bounds = (
                                    -left,
                                    -top,
                                    dc.GetDeviceCaps(110) - left,
                                    dc.GetDeviceCaps(111) - top,
                                )
                                ImageWin.Dib(image).draw(dc.GetHandleOutput(), bounds)
                                dc.EndPage()
                            finally:
                                image.close()
                                bitmap.close()
                                page.close()
                    dc.EndDoc()
                finally:
                    document.close()
            except BaseException:
                dc.AbortDoc()
                raise
        return reference
