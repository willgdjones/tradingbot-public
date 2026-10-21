"""Bounded retry and pacing for public GET requests only."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Callable

from .archive import Request


class FetchError(RuntimeError):
    def __init__(self, status: int | None, retry_after: str | None = None):
        super().__init__(f"public data request failed (HTTP {status or 'connection error'})")
        self.status, self.retry_after = status, retry_after


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 0
        if not math.isfinite(delay):
            delay = 0
        # Never retry earlier than a server's long Retry-After; leave job resumable.
        if delay > 60:
            raise FetchError(429, value)
        return max(0.5, delay)
    return min(30.0, 2.0 ** attempt)


class RetryingGetter:
    def __init__(self, fetch: Callable[[Request], str], *, attempts: int = 5,
                 interval: float = 0.25, sleep: Callable[[float], None] = time.sleep):
        if attempts < 1 or interval < 0:
            raise ValueError("invalid retry/pacing settings")
        self.fetch, self.attempts, self.interval, self.sleep = fetch, attempts, interval, sleep

    def __call__(self, request: Request) -> str:
        for attempt in range(self.attempts):
            self.sleep(self.interval)
            try:
                return self.fetch(request)
            except FetchError as error:
                if (error.status is not None and error.status not in {408, 429, 500, 502, 503, 504}
                        or attempt == self.attempts - 1):
                    raise
                self.sleep(retry_delay(error.retry_after, attempt))
        raise AssertionError("unreachable")
