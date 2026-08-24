"""
app.py -- an API gateway demo that applies rate limiting per client
(identified by an API key header) in front of a couple of dummy
upstream routes, returning 429 with a Retry-After header when a client
exceeds its limit -- the standard HTTP contract for rate-limited APIs.

Uses the in-memory TokenBucket by default (single-process demo). Swap
in DistributedFixedWindowLimiter + a real Redis connection for a
multi-instance deployment -- see README.
"""

import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from algorithms.token_bucket import TokenBucket

app = FastAPI(title="RateLimiter-Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# per-tier limits: free tier gets a small bucket, paid tier a bigger one
LIMITERS = {
    "free": TokenBucket(capacity=5, refill_rate=1.0),     # burst 5, refill 1/sec
    "paid": TokenBucket(capacity=50, refill_rate=10.0),    # burst 50, refill 10/sec
}


def get_client_tier(request: Request) -> tuple[str, str]:
    api_key = request.headers.get("X-API-Key", "anonymous")
    tier = request.headers.get("X-Tier", "free")
    if tier not in LIMITERS:
        tier = "free"
    return api_key, tier


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/status"):
        return await call_next(request)

    client_id, tier = get_client_tier(request)
    limiter = LIMITERS[tier]

    if not limiter.allow(client_id):
        retry_after = limiter.retry_after_seconds(client_id)
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded", "retry_after_seconds": retry_after},
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(limiter.tokens_remaining(client_id))
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status(request: Request):
    """Check remaining quota without consuming a token (exempted from
    the rate limit itself, same as /health)."""
    client_id, tier = get_client_tier(request)
    limiter = LIMITERS[tier]
    return {
        "client_id": client_id, "tier": tier,
        "tokens_remaining": limiter.tokens_remaining(client_id),
        "capacity": limiter.capacity,
    }


@app.get("/api/data")
def get_data():
    return {"data": "this is a rate-limited upstream endpoint", "timestamp": time.time()}


@app.get("/api/expensive")
def expensive_operation():
    return {"result": "this endpoint simulates a costly operation", "timestamp": time.time()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8014, reload=True)
