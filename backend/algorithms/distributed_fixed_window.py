"""
distributed_fixed_window.py -- a Redis-backed distributed rate limiter,
so multiple gateway instances (behind a load balancer) share limit
state instead of each process tracking its own independent counter
(which would let a client get N times the intended limit by hitting N
different gateway instances).

Uses Redis's native INCR + EXPIRE, which is the standard real-world
pattern for this: INCR is atomic on its own (Redis is single-threaded
per command), so "increment and read the new value" never races between
concurrent requests, even from different processes. This avoids needing
Lua scripting (EVAL) for the fixed-window case -- Lua/EVALSHA becomes
necessary once you need multi-step atomic logic (like token bucket's
read-refill-write sequence), which is deliberately noted as the
production next step rather than shipped unverified here (this
sandbox's Redis test double doesn't support EVAL, so rather than ship
an "atomic" claim I couldn't actually verify, this implementation uses
the primitive that IS verifiable: see README for the tradeoff).
"""

import math
import redis


class DistributedFixedWindowLimiter:
    def __init__(self, redis_client: "redis.Redis", limit: int, window_seconds: int,
                 key_prefix: str = "ratelimit:"):
        self.redis = redis_client
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix

    def _key(self, client_id: str, now: float) -> str:
        window_index = int(now // self.window_seconds)
        return f"{self.key_prefix}{client_id}:{window_index}"

    def allow(self, client_id: str, now: float = None) -> bool:
        import time
        now = now if now is not None else time.time()
        key = self._key(client_id, now)

        count = self.redis.incr(key)
        if count == 1:
            # first request in this window on ANY gateway instance --
            # set the expiry so old window keys don't accumulate forever
            self.redis.expire(key, math.ceil(self.window_seconds) + 5)

        return count <= self.limit

    def current_count(self, client_id: str, now: float = None) -> int:
        import time
        now = now if now is not None else time.time()
        key = self._key(client_id, now)
        val = self.redis.get(key)
        return int(val) if val else 0
