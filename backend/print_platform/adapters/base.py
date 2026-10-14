from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class PrinterAdapter(Protocol):
    def capabilities(self, orientation: str) -> dict: ...
    def device_status(self) -> dict: ...
    def submit(self, pdf: Path, copies: int, orientation: str, marker: str, on_job: Callable): ...
    def query_job(self, reference: dict) -> dict: ...
    def find_job(self, marker: str) -> dict | None: ...
    def cancel_job(self, reference: dict): ...


class DisabledPrinter:
    def capabilities(self, orientation="portrait"):
        landscape = orientation == "landscape"
        return {
            "cancel_supported": False,
            "geometry": {
                "version": "p1106-report-20261013-provisional",
                "source": "report",
                "width_mm": 297.011 if landscape else 210.016,
                "height_mm": 210.016 if landscape else 297.011,
                "printable_width_mm": 289.010 if landscape else 203.200,
                "printable_height_mm": 203.200 if landscape else 289.010,
                "left_mm": 3.979,
                "top_mm": 2.836 if landscape else 3.979,
            },
        }

    def device_status(self):
        return {"available": False, "blocked": True, "message": "打印适配器未启用", "toner": "unknown"}

    def find_job(self, marker):
        return None

    def query_job(self, reference):
        raise RuntimeError("打印适配器未启用")

    def submit(self, *args):
        raise RuntimeError("打印适配器未启用")

    def cancel_job(self, reference):
        raise RuntimeError("打印适配器未启用")
