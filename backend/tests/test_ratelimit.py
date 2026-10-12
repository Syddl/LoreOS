"""Fixed-window rate limits: the count, the refund, the window boundary and concurrent calls, on a patched clock."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from conftest import sql
from loreos import ratelimit

T0 = datetime(2026, 1, 1, tzinfo=UTC)  # a whole minute, so the start of a 60 s window


@pytest.fixture
def clock(clean, monkeypatch):
    """Set .t to move ratelimit's clock."""
    now = SimpleNamespace(t=T0)
    monkeypatch.setattr(ratelimit, "_now", lambda: now.t)
    return now


def call(bucket="b", limit=3):
    return asyncio.run(ratelimit.rate_limit(bucket, limit, 60))


def refund(slot, bucket="b"):
    asyncio.run(ratelimit.refund(bucket, slot.window_start))


def counts(bucket="b"):
    return sql("select window_start, count from loreos.rate_limits where bucket = :b order by window_start", b=bucket)


def test_three_calls_are_allowed_and_the_fourth_is_refused_until_the_window_ends(clock):
    clock.t = T0 + timedelta(seconds=20.5)
    slots = [call() for _ in range(4)]
    assert [s.allowed for s in slots] == [True, True, True, False]
    assert [s.retry_after for s in slots] == [0, 0, 0, 40]  # 39.5 s left, rounded up so it is never 0
    assert {s.window_start for s in slots} == {T0}


def test_a_refund_lets_one_more_call_through(clock):
    slots = [call() for _ in range(3)]
    refund(slots[0])
    assert call().allowed
    assert not call().allowed


def test_a_refund_never_takes_the_count_below_0(clock):
    slot = call()
    refund(slot)
    refund(slot)
    assert counts() == [(T0, 0)]
    assert [call().allowed for _ in range(4)] == [True, True, True, False]


def test_a_refund_after_the_boundary_returns_the_slot_to_its_own_window(clock):
    clock.t = T0 + timedelta(seconds=59)
    first = call()
    clock.t = T0 + timedelta(seconds=61)
    call()
    refund(first)
    assert counts() == [(T0, 0), (T0 + timedelta(seconds=60), 1)]


def test_the_next_window_allows_again(clock):
    assert not [call() for _ in range(4)][-1].allowed
    clock.t = T0 + timedelta(seconds=60)
    slot = call()
    assert slot.allowed and slot.window_start == clock.t


def test_concurrent_calls_count_each_one(clock):
    async def burst():
        return await asyncio.gather(*(ratelimit.rate_limit("b", 5, 60) for _ in range(10)))

    slots = asyncio.run(burst())
    assert counts() == [(T0, 10)]
    assert sum(s.allowed for s in slots) == 5


def test_buckets_are_independent(clock):
    assert [call("a", 1).allowed for _ in range(2)] == [True, False]
    assert call("c", 1).allowed
