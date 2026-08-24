import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.algorithms.token_bucket import TokenBucket
from backend.algorithms.sliding_window import SlidingWindowLog, SlidingWindowCounter
from backend.algorithms.fixed_window import FixedWindowCounter


# ---------------------------------------------------------------- Token Bucket

def test_token_bucket_allows_up_to_capacity():
    tb = TokenBucket(capacity=5, refill_rate=1.0)
    now = 1000.0
    results = [tb.allow("client1", now=now) for _ in range(5)]
    assert all(results)
    assert tb.allow("client1", now=now) is False  # 6th request denied


def test_token_bucket_refills_over_time():
    tb = TokenBucket(capacity=5, refill_rate=1.0)  # 1 token/sec
    now = 1000.0
    for _ in range(5):
        tb.allow("client1", now=now)
    assert tb.allow("client1", now=now) is False
    # 3 seconds later, 3 tokens should have refilled
    assert tb.allow("client1", now=now + 3.0) is True
    assert tb.allow("client1", now=now + 3.0) is True
    assert tb.allow("client1", now=now + 3.0) is True
    assert tb.allow("client1", now=now + 3.0) is False  # only 3 refilled


def test_token_bucket_separate_clients_independent():
    tb = TokenBucket(capacity=2, refill_rate=1.0)
    now = 1000.0
    assert tb.allow("alice", now=now) is True
    assert tb.allow("alice", now=now) is True
    assert tb.allow("alice", now=now) is False
    assert tb.allow("bob", now=now) is True  # bob has his own bucket


def test_token_bucket_retry_after_calculation():
    tb = TokenBucket(capacity=1, refill_rate=2.0)  # refills 1 token every 0.5s
    now = 1000.0
    tb.allow("client1", now=now)  # consume the only token
    retry = tb.retry_after_seconds("client1", now=now)
    assert 0.4 <= retry <= 0.6


def test_token_bucket_never_exceeds_capacity_on_long_idle():
    tb = TokenBucket(capacity=3, refill_rate=10.0)
    now = 1000.0
    tb.allow("client1", now=now)
    # even after a huge idle gap, bucket caps at capacity, not unbounded
    assert tb.tokens_remaining("client1", now=now + 10000) == 3


# ---------------------------------------------------------------- Sliding Window Log

def test_sliding_window_log_exact_limit():
    sw = SlidingWindowLog(limit=3, window_seconds=10)
    now = 1000.0
    assert sw.allow("c1", now=now) is True
    assert sw.allow("c1", now=now + 1) is True
    assert sw.allow("c1", now=now + 2) is True
    assert sw.allow("c1", now=now + 3) is False  # 4th within window


def test_sliding_window_log_old_entries_expire():
    sw = SlidingWindowLog(limit=2, window_seconds=5)
    now = 1000.0
    sw.allow("c1", now=now)
    sw.allow("c1", now=now + 1)
    assert sw.allow("c1", now=now + 2) is False
    # 6 seconds later, the first two requests have fallen out of the window
    assert sw.allow("c1", now=now + 6) is True


def test_sliding_window_log_no_boundary_burst_flaw():
    """The exact log-based limiter should NOT allow 2x the limit across
    a window boundary (unlike fixed window -- see the comparison test)."""
    sw = SlidingWindowLog(limit=5, window_seconds=10)
    now = 1000.0
    for i in range(5):
        assert sw.allow("c1", now=now + 9.9) is True
    # still within 10s of the earlier requests -- should be denied
    assert sw.allow("c1", now=now + 10.5) is False


# ---------------------------------------------------------------- Sliding Window Counter

def test_sliding_window_counter_respects_limit_within_one_window():
    sw = SlidingWindowCounter(limit=5, window_seconds=10)
    now = 1000.0  # aligned window start
    allowed = [sw.allow("c1", now=now + i * 0.1) for i in range(5)]
    assert all(allowed)
    assert sw.allow("c1", now=now + 0.6) is False


def test_sliding_window_counter_smooths_boundary_vs_fixed_window():
    """At a window boundary, the weighted counter should allow noticeably
    FEWER requests than naive fixed-window double-counting (5+5=10 in a
    tiny span) -- demonstrating why it's preferred over fixed window."""
    limit, window = 5, 10
    sw = SlidingWindowCounter(limit=limit, window_seconds=window)
    fw = FixedWindowCounter(limit=limit, window_seconds=window)

    base = 1000.0  # aligned to a window boundary multiple of `window`
    # fill up the window ending right at the boundary
    for i in range(limit):
        sw.allow("c1", now=base - 0.1)
        fw.allow("c1", now=base - 0.1)

    # immediately after the boundary, try to burst `limit` more requests
    sw_allowed = sum(1 for i in range(limit) if sw.allow("c1", now=base + 0.05 + i * 0.001))
    fw_allowed = sum(1 for i in range(limit) if fw.allow("c1", now=base + 0.05 + i * 0.001))

    assert fw_allowed == limit  # fixed window: full second burst allowed (the flaw)
    assert sw_allowed < fw_allowed  # sliding window counter smooths this out


# ---------------------------------------------------------------- Fixed Window

def test_fixed_window_resets_on_new_window():
    fw = FixedWindowCounter(limit=3, window_seconds=10)
    now = 1000.0  # window [1000, 1010)
    assert fw.allow("c1", now=now) is True
    assert fw.allow("c1", now=now) is True
    assert fw.allow("c1", now=now) is True
    assert fw.allow("c1", now=now) is False
    assert fw.allow("c1", now=now + 10) is True  # new window


def test_fixed_window_demonstrates_boundary_burst_flaw():
    """Documents the known flaw: up to 2x limit requests can succeed in
    a short span straddling a window boundary."""
    fw = FixedWindowCounter(limit=5, window_seconds=10)
    base = 1000.0
    for _ in range(5):
        assert fw.allow("c1", now=base - 0.1) is True   # end of window N
    for _ in range(5):
        assert fw.allow("c1", now=base + 0.1) is True   # start of window N+1
    # 10 requests succeeded within a 0.2s span -- 2x the intended limit
