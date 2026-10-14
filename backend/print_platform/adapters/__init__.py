from functools import lru_cache

from ..config import config
from .base import DisabledPrinter


@lru_cache
def adapter():
    options = config().printer
    if options.backend == "windows":
        from .windows import WindowsPrinter

        return WindowsPrinter(options.queue, options.cancel_verified)
    return DisabledPrinter()
