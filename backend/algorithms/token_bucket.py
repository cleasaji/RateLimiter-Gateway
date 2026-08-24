"""
token_bucket.py -- the token bucket algorithm: each client has a bucket
that holds up to `capacity` tokens, refilling at `refill_rate` tokens/
second. Each request consumes one token; if the bucket is empty, the
request is rejected. This is the algorithm most production rate
limiters use (AWS, Stripe) because it naturally allows short bursts up
to `capacity` while enforcing a steady average rate over time.
"""

import time
import threading


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        """
        capacity: max tokens the bucket can hold (= max burst size)
        refill_rate: tokens added per second (= sustained allowed rate)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: dict[str, tuple[float, float]] = {}  # client_id -> (tokens, last_refill_ts)
        self._lock = threading.Lock()

    def _refill(self, client_id: str, now: float) -> float:
        tokens, last_refill = self._buckets.get(client_id, (self.capacity, now))
        elapsed = max(0.0, now - last_refill)
        tokens = min(self.capacity, tokens + elapsed * self.refill_rate)
        return tokens

    def allow(self, client_id: str, cost: float = 1.0, now: float = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            tokens = self._refill(client_id, now)
            if tokens >= cost:
                tokens -= cost
                self._buckets[client_id] = (tokens, now)
                return True
            self._buckets[client_id] = (tokens, now)
            return False

    def tokens_remaining(self, client_id: str, now: float = None) -> float:
        now = now if now is not None else time.time()
        with self._lock:
            return round(self._refill(client_id, now), 4)

    def retry_after_seconds(self, client_id: str, cost: float = 1.0, now: float = None) -> float:
        now = now if now is not None else time.time()
        tokens = self.tokens_remaining(client_id, now)
        if tokens >= cost:
            return 0.0
        needed = cost - tokens
        return round(needed / self.refill_rate, 4)
