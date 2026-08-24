# 🚦 RateLimiter-Gateway

A **distributed API rate limiter and gateway** implementing four
rate-limiting algorithms (token bucket, sliding window log, sliding
window counter, fixed window) plus a Redis-backed distributed version
— one of the most commonly asked systems-design interview questions at
every major tech company, and a real production concern for any
API-facing service.

> General software-engineering portfolio project (not AI/cybersecurity)
> — infra/systems-design fundamentals.

---

## The four algorithms, and why each exists

| Algorithm | Memory cost | Accuracy | The tradeoff |
|---|---|---|---|
| **Fixed Window** | O(1) per client | Has a boundary flaw | Simplest, but allows up to 2x the limit in a burst straddling a window boundary — demonstrated explicitly in tests |
| **Sliding Window Log** | O(requests in window) | Exact | Perfectly accurate, but memory scales with request volume per client |
| **Sliding Window Counter** | O(1) per client | Approximate | The production compromise — weights the previous window's count to estimate the sliding total, avoiding the log's memory cost |
| **Token Bucket** | O(1) per client | Allows controlled bursts | What most production APIs actually use (Stripe, AWS) — a `capacity`-sized burst allowance on top of a steady refill rate |

**The fixed-window flaw is proven, not just described**: a test sends 5
requests at the end of one window and 5 more immediately after the
boundary — fixed window allows all 10 in a ~0.2 second span (2x the
intended rate), while the sliding window counter allows visibly fewer.
Both behaviors are asserted directly in `test_algorithms.py`.

## Distributed deployment: a tradeoff stated honestly

A real gateway runs multiple instances behind a load balancer — an
in-memory limiter alone would let a client get N× the limit by hitting
N different instances. The fix is a shared Redis backend.

The natural choice for token bucket's read-refill-write logic is a Lua
script executed atomically via `EVAL` — but this sandbox's Redis test
double (`fakeredis`) doesn't support Lua scripting, so **rather than
ship an "atomic" implementation I couldn't actually verify**,
`distributed_fixed_window.py` uses Redis's native `INCR`/`EXPIRE`
instead — genuinely atomic (Redis is single-threaded per command), and
fully testable. `test_distributed_limiter_concurrent_incr_is_atomic`
proves 100 simulated concurrent calls yield exactly the limit, never
more. The Lua-based distributed token bucket is the natural next step
for a real deployment with real Redis — documented here rather than
shipped untested.

## Project structure

```
RateLimiter-Gateway/
├── backend/
│   ├── algorithms/
│   │   ├── token_bucket.py              # in-memory, burst + steady rate
│   │   ├── sliding_window.py             # log (exact) + counter (approximate)
│   │   ├── fixed_window.py                # simplest, boundary flaw demonstrated
│   │   └── distributed_fixed_window.py     # Redis-backed, multi-instance shared state
│   ├── app.py                                # FastAPI gateway: 429 + Retry-After, per-tier limits
│   ├── tests/
│   │   ├── test_algorithms.py                  # 12 tests incl. boundary-flaw comparison
│   │   └── test_distributed.py                   # 6 tests against fakeredis
├── frontend/
│   └── index.html                                  # live bucket visualization + burst demo
├── requirements.txt
└── README.md
```

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd backend
python -m pytest tests/ -q   # 18/18 should pass
python app.py                 # FastAPI gateway on http://localhost:8014
```

Open `frontend/index.html`, pick a tier, and click **Burst 10
requests** to watch the bucket empty and hit `429`s, then refill over
time.

```bash
# example: burst past the free-tier limit (capacity 5)
for i in {1..7}; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8014/api/data \
    -H "X-API-Key: demo" -H "X-Tier: free"
done
# 200 200 200 200 200 429 429
```

## What's tested (18 tests)

Token bucket: capacity enforcement, refill-over-time accuracy, per-
client independence, retry-after calculation, capping at capacity on
long idle. Sliding window log: exact limit enforcement, old-entry
expiry, no boundary-burst flaw. Sliding window counter: within-window
correctness, **smoothing comparison against fixed window's flaw**.
Fixed window: reset on new window, **the boundary flaw demonstrated
explicitly**. Distributed: limit enforcement, window reset, **state
shared across two simulated gateway instances** (the actual point of
going distributed), per-client independence, count reporting, and
**atomicity under 100 simulated concurrent requests**.

## What to say about this in an interview

- "I implemented all four standard rate-limiting algorithms and wrote
  tests that prove the tradeoff between them — not just describe it —
  including a test that shows fixed window allowing 2x burst at a
  boundary, and the sliding window counter measurably reducing that."
- Be ready to explain why token bucket is the production standard
  (controlled burst tolerance) and why distributed deployment needs
  shared state (multiple gateway instances otherwise each enforce the
  limit independently).
- Be upfront about the Lua/EVAL limitation in this sandbox and what the
  production-grade distributed token bucket would look like — shows you
  understand atomicity requirements, not just that you avoided the hard
  part.

## License

MIT — see `LICENSE`.
