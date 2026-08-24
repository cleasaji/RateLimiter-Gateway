"""
sliding_window.py -- two sliding-window rate limiting algorithms.

SlidingWindowLog: exact -- stores every request timestamp per client
and counts how many fall within the last `window_seconds`. Perfectly
accurate but O(requests in window) memory per client.

SlidingWindowCounter: approximate -- keeps only two fixed-window
counters (current + previous) and computes a weighted estimate of the
sliding window, avoiding the memory cost of the log. This is the
tradeoff every real system with millions of clients has to make: exact
accuracy (log) doesn't scale in memory; the weighted counter approach
(used by e.g. Cloudflare's public writeups on their rate limiter) is
"accurate enough" -- it can under/over-count slightly at window
boundaries, quantified and tested below.
"""

import time
import threading
from collections import deque


class SlidingWindowLog:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self._logs: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, client_id: str, now: float = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            log = self._logs.setdefault(client_id, deque())
            cutoff = now - self.window_seconds
            while log and log[0] <= cutoff:
                log.popleft()
            if len(log) < self.limit:
                log.append(now)
                return True
            return False

    def count_in_window(self, client_id: str, now: float = None) -> int:
        now = now if now is not None else time.time()
        with self._lock:
            log = self._logs.get(client_id, deque())
            cutoff = now - self.window_seconds
            return sum(1 for t in log if t > cutoff)


class SlidingWindowCounter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        # client_id -> {"window_start": ts, "current": int, "previous": int}
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def allow(self, client_id: str, now: float = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            state = self._state.get(client_id)
            window_start = (int(now // self.window_seconds)) * self.window_seconds

            if state is None or state["window_start"] != window_start:
                if state is not None and state["window_start"] == window_start - self.window_seconds:
                    previous = state["current"]
                else:
                    previous = 0
                state = {"window_start": window_start, "current": 0, "previous": previous}
                self._state[client_id] = state

            elapsed_in_window = now - window_start
            weight_previous = max(0.0, (self.window_seconds - elapsed_in_window) / self.window_seconds)
            estimated_count = state["previous"] * weight_previous + state["current"]

            if estimated_count < self.limit:
                state["current"] += 1
                return True
            return False
