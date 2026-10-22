import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
log = logging.getLogger("jinni.retry")


def with_retries(fn: Callable[[], T], attempts: int, base_delay: float, retry_on: tuple[type[Exception], ...],) -> T:
    for attempt in range(1, attempts):
        try:
            return fn()
        except retry_on as e:
            delay = base_delay * 2 ** (attempt - 1)
            log.warning("attemp %d/%d failed (%s), retrying in %.1fs", attempt, attempts, type(e).__name__, delay)
            print(f"  (server hiccup, retrying in {delay:.0f}s... {attempt}/{attempts})")
            time.sleep(delay)
    return fn()