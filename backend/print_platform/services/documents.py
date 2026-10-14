import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject

from ..config import config
from ..errors import AppError
from ..services.storage import ensure_space, root, temp_path


def verify_pdf(path, limit):
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise AppError("encrypted_pdf", "不支持加密 PDF")
    if not 1 <= len(reader.pages) <= limit:
        raise AppError("page_limit", "原文页数超过上限")
    for page in reader.pages:
        width, height = float(page.cropbox.width), float(page.cropbox.height)
        if not 0 < width <= 14400 or not 0 < height <= 14400:
            raise AppError("invalid_pdf", "PDF 页面尺寸异常")
    return len(reader.pages)


def normalize(source: Path, ext: str, limits: dict):
    if ext == ".pdf":
        return source, verify_pdf(source, limits["max_source_pages"]), "pdf-original-v1"
    output = temp_path(".pdf")
    try:
        if ext in {".png", ".jpg", ".jpeg", ".bmp"}:
            with Image.open(source) as image:
                expected = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".bmp": "BMP"}[ext]
                if image.format != expected or image.width * image.height > limits["max_image_pixels"]:
                    raise AppError("invalid_image", "图片格式或像素数量不符合要求")
                rgb = image.convert("RGB")
                try:
                    rgb.save(output, "PDF", resolution=150)
                finally:
                    rgb.close()
            version = "pillow-image-v1"
        else:
            program = config().converter.office_program
            if not program or not Path(program).is_absolute() or not Path(program).is_file():
                raise AppError("converter_unavailable", "尚未配置 LibreOffice 转换器")
            # New profile per invocation. Never attach to an interactive Office instance.
            with tempfile.TemporaryDirectory(dir=root() / "tmp") as work:
                import shutil

                directory = Path(work)
                profile = directory / "profile"
                source_copy = directory / ("input" + ext)
                shutil.copyfile(source, source_copy)
                subprocess.run(
                    [
                        program,
                        "-env:UserInstallation=" + profile.as_uri(),
                        "--headless",
                        "--nologo",
                        "--norestore",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(directory),
                        str(source_copy),
                    ],
                    check=True,
                    timeout=limits["conversion_timeout_seconds"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
                result = directory / "input.pdf"
                if not result.exists():
                    raise AppError("conversion_failed", "转换未生成 PDF")
                os.replace(result, output)
            version = "libreoffice-first-result-v1"
        ensure_space(limits)
        return output, verify_pdf(output, limits["max_source_pages"]), version
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def plan_storage_key(sha256, pages, geometry, scaling):
    payload = json.dumps([sha256, pages, geometry, scaling, "layout-form-v3"], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"plans/{digest}.pdf"


def make_plan(source: Path, pages, geometry, scaling, limits):
    factor = 72 / 25.4
    width, height = geometry["width_mm"] * factor, geometry["height_mm"] * factor
    left = geometry["left_mm"] * factor
    printable_width, printable_height = (
        geometry["printable_width_mm"] * factor,
        geometry["printable_height_mm"] * factor,
    )
    bottom = height - (geometry["top_mm"] + geometry["printable_height_mm"]) * factor
    reader, writer = PdfReader(source), PdfWriter()
    forms = {}
    for number in pages:
        original = reader.pages[number - 1]
        box = original.cropbox
        crop_left, crop_bottom, crop_right, crop_top = map(float, box)
        rotation = original.rotation % 360
        matrices = {
            0: (1, 0, 0, 1, -crop_left, -crop_bottom),
            90: (0, -1, 1, 0, -crop_bottom, crop_right),
            180: (-1, 0, 0, -1, crop_right, crop_top),
            270: (0, 1, -1, 0, crop_top, -crop_left),
        }
        if rotation not in matrices:
            raise AppError("invalid_pdf", "PDF 页面旋转角度异常")
        original_width, original_height = crop_right - crop_left, crop_top - crop_bottom
        if rotation in (90, 270):
            original_width, original_height = original_height, original_width
        if scaling == "fit":
            scale = min(printable_width / original_width, printable_height / original_height)
            x, y = (
                (printable_width - original_width * scale) / 2,
                (printable_height - original_height * scale) / 2,
            )
        else:
            factors = {"actual": 1, "75%": .75, "50%": .5, "25%": .25}
            if scaling not in factors:
                raise AppError("invalid_scaling", "缩放选项无效")
            scale = factors[scaling]
            x, y = (width - original_width * scale) / 2 - left, (height - original_height * scale) / 2 - bottom
        # Wrap the original content as a reusable vector form. Avoid parsing/re-writing
        # every drawing operator twice; resources are cloned once by PdfWriter.
        if number not in forms:
            form = DecodedStreamObject()
            content = original.get_contents()
            form.set_data(content.get_data() if content is not None else b"")
            form.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([FloatObject(v) for v in (crop_left, crop_bottom, crop_right, crop_top)]),
                NameObject("/Resources"): original.get("/Resources", DictionaryObject()).clone(writer),
            })
            if "/Group" in original:
                form[NameObject("/Group")] = original["/Group"].clone(writer)
            forms[number] = writer._add_object(form.flate_encode())
        full = writer.add_blank_page(width=width, height=height)
        full[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Source"): forms[number]})
        })
        a, bb, c, d, e, f = matrices[rotation]
        matrix = (a * scale, bb * scale, c * scale, d * scale, e * scale + x + left, f * scale + y + bottom)
        stream = DecodedStreamObject()
        def numbers(values):
            return " ".join(f"{v:.9f}" for v in values)
        stream.set_data((
            f"q {numbers((left, bottom, printable_width, printable_height))} re W n "
            f"{numbers(matrix)} cm /Source Do Q\n"
        ).encode("ascii"))
        full[NameObject("/Contents")] = writer._add_object(stream)
    output = temp_path(".pdf")
    try:
        ensure_space(limits)
        writer.write(output)
        ensure_space(limits)
        return output
    except BaseException:
        output.unlink(missing_ok=True)
        raise
