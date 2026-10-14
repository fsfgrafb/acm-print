import calendar
import re
from datetime import UTC
from zoneinfo import ZoneInfo

ACTIVE_STATES = {"queued", "submitting", "submitted", "printing", "cancelling", "unknown"}
SETTINGS = {
    "max_copies": (20, 1, 100),
    "storage_limit_gb": (512, 1, 100000),
    "cleanup_target_percent": (90, 10, 99),
    "min_password_length": (4, 4, 128),
    "max_file_mib": (50, 1, 1024),
    "max_batch_files": (10, 1, 100),
    "max_source_pages": (500, 1, 10000),
    "max_plan_pages": (1000, 1, 10000),
    "max_image_pixels": (40000000, 1000000, 100000000),
    "temporary_budget_mib": (200, 1, 10000),
    "conversion_timeout_seconds": (120, 10, 600),
    "poll_seconds": (5, 1, 60),
    "session_days": (30, 1, 365),
    "temporary_hours": (24, 1, 168),
    "idempotency_days": (30, 1, 365),
}


def settings(state):
    return {key: state.settings.get(key, default) for key, (default, _, _) in SETTINGS.items()}


def validate_identity(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", value):
        raise ValueError("需为 4–64 位字母、数字、连字符或下划线")
    return value


def validate_email(value: str) -> str:
    value = value.strip()
    if value and (
        len(value) > 254
        or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value)
        or value.split("@")[0].startswith(".") or value.split("@")[0].endswith(".") or ".." in value
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    ):
        raise ValueError("邮箱格式不正确")
    return value


def validate_phone(value: str) -> str:
    value = value.strip()
    if value and not re.fullmatch(r"(?:\+?86)?1[3-9][0-9]{9}", value):
        raise ValueError("手机号需为 11 位中国大陆手机号，可带 +86 前缀")
    return value


def four_years(created):
    local = created.astimezone(ZoneInfo("Asia/Shanghai"))
    year = local.year + 4
    day = min(local.day, calendar.monthrange(year, local.month)[1])
    return local.replace(year=year, day=day).astimezone(UTC)


def selected_pages(mode: str, expression: str, count: int, limit: int) -> list[int]:
    if mode == "all":
        pages = list(range(1, count + 1))
    elif mode in {"odd", "even"}:
        pages = list(range(1 if mode == "odd" else 2, count + 1, 2))
    elif mode == "custom":
        pages = []
        for part in re.split(r"[,，\s]+", expression.strip()):
            if not re.fullmatch(r"\d+(?:-\d+)?", part):
                raise ValueError("页码格式错误")
            bounds = [int(v) for v in part.split("-")]
            start, end = bounds[0], bounds[-1]
            if not 1 <= start <= end <= count:
                raise ValueError("页码越界或范围倒序")
            if len(pages) + end - start + 1 > limit:
                raise ValueError("选页数量超过上限")
            pages.extend(range(start, end + 1))
    else:
        raise ValueError("选页模式错误")
    if not pages or len(pages) > limit:
        raise ValueError("选页为空或超过上限")
    return pages
