"""Tiny sliding-window rate limiter shared by the API clients.

Adapted from cvxv666/fomo-robinhood-radar (MIT), fomo_agent/ratelimit.py
Copyright (c) 2026 fomo-agent contributors. Trimmed to the in-process limiter: this tool runs
as one process, so the SQLite-backed box-wide window of the original is not needed.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, max_per_min: int, name: str = "api", sleep=None, clock=time.monotonic):
        self.max = max_per_min
        self.name = name
        self.calls: deque[float] = deque()
        self.total = 0
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self._clock = clock
        # Sleeping with the lock held is the point: a second caller arriving during the wait
        # queues behind it instead of also deciding there is room.
        self._lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()

    def take(self) -> bool:
        """Claim a slot if there is one, without waiting."""
        with self._lock:
            now = self._clock()
            self._trim(now)
            if len(self.calls) >= self.max:
                return False
            self.calls.append(now)
            self.total += 1
            return True

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            self._trim(now)
            if len(self.calls) >= self.max:
                pause = 60 - (now - self.calls[0]) + 0.05
                log.info("%s rate limit: sleeping %.1fs", self.name, pause)
                self._sleep(max(pause, 0))
                self._trim(self._clock())
            self.calls.append(self._clock())
            self.total += 1
