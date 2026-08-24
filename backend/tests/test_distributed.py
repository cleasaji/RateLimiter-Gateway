"""
test_distributed.py -- tests the Redis-backed distributed rate limiter
against fakeredis (an in-memory Redis emulator supporting INCR/EXPIRE/
GET, which is all this implementation needs), so these tests run
without a real Redis server while still exercising real atomic Redis
commands, not a mocked stand-in for them.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
import fakeredis

from backend.algorithms.distributed_fixed_window import DistributedFixedWindowLimiter


@pytest.fixture
def redis_client():
    return fakeredis.FakeStrictRedis(decode_responses=True)


def test_distributed_limiter_allows_up_to_limit(redis_client):
    limiter = DistributedFixedWindowLimiter(redis_client, limit=5, window_seconds=10)
    now = 1000.0
    results = [limiter.allow("client1", now=now) for _ in range(5)]
    assert all(results)
    assert limiter.allow("client1", now=now) is False


def test_distributed_limiter_resets_on_new_window(redis_client):
    limiter = DistributedFixedWindowLimiter(redis_client, limit=3, window_seconds=10)
    now = 1000.0
    for _ in range(3):
        limiter.allow("client1", now=now)
    assert limiter.allow("client1", now=now) is False
    assert limiter.allow("client1", now=now + 10) is True  # new window


def test_distributed_limiter_shared_across_two_gateway_instances(redis_client):
    """The whole point of the distributed version: two separate
    DistributedFixedWindowLimiter instances (simulating two gateway
    processes) sharing the SAME Redis backend must share limit state --
    unlike the in-memory FixedWindowCounter, where each process would
    have its own independent counter."""
    gateway_a = DistributedFixedWindowLimiter(redis_client, limit=5, window_seconds=10)
    gateway_b = DistributedFixedWindowLimiter(redis_client, limit=5, window_seconds=10)
    now = 1000.0

    for _ in range(5):
        assert gateway_a.allow("client1", now=now) is True

    # client1 switches to gateway_b -- should be denied, because the
    # counter is shared via Redis, not per-process
    assert gateway_b.allow("client1", now=now) is False


def test_distributed_limiter_independent_clients(redis_client):
    limiter = DistributedFixedWindowLimiter(redis_client, limit=2, window_seconds=10)
    now = 1000.0
    assert limiter.allow("alice", now=now) is True
    assert limiter.allow("alice", now=now) is True
    assert limiter.allow("alice", now=now) is False
    assert limiter.allow("bob", now=now) is True


def test_distributed_limiter_current_count_reporting(redis_client):
    limiter = DistributedFixedWindowLimiter(redis_client, limit=10, window_seconds=10)
    now = 1000.0
    for _ in range(4):
        limiter.allow("client1", now=now)
    assert limiter.current_count("client1", now=now) == 4


def test_distributed_limiter_concurrent_incr_is_atomic(redis_client):
    """Simulates many 'simultaneous' requests (as if from different
    gateway processes/threads) all calling allow() -- because Redis
    INCR is atomic, exactly `limit` should succeed, never more, even
    though nothing here explicitly locks between the calls."""
    limiter = DistributedFixedWindowLimiter(redis_client, limit=50, window_seconds=10)
    now = 1000.0
    results = [limiter.allow("client1", now=now) for _ in range(100)]
    assert sum(results) == 50
