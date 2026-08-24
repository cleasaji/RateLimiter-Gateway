"""
fixed_window.py -- the simplest rate limiter: count requests in a fixed
time bucket (e.g. "this minute"), reset to zero when the bucket rolls
over. Cheapest to implement and reason about, but has a well-known
boundary-burst flaw: a client can send `limit` requests at 0:59 and
another `limit` at 1:00, getting 2x the intended rate in a 1-second
span straddling the boundary. Included here specifically so that flaw
can be demonstrated and compared against the sliding window
alternatives in the same test suite.
"""

import time
import threading


class FixedWindowCounter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self._state: dict[str, tuple[int, int]] = {}  # client_id -> (window_index, count)
        self._lock = threading.Lock()

    def allow(self, client_id: str, now: float = None) -> bool:
        now = now if now is not None else time.time()
        window_index = int(now // self.window_seconds)
        with self._lock:
            stored_window, count = self._state.get(client_id, (window_index, 0))
            if stored_window != window_index:
                count = 0
                stored_window = window_index
            if count < self.limit:
                count += 1
                self._state[client_id] = (stored_window, count)
                return True
            self._state[client_id] = (stored_window, count)
            return False
