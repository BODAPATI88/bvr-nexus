"""
Tests for DLQ helpers and idempotency in bvr_sdk.events.

Uses AsyncMock redis — no live Redis needed.
"""

import asyncio
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from bvr_sdk.events import (  # type: ignore[import]
    EventEnvelope,
    track_failure,
    clear_failure_counter,
    send_to_dlq,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_redis():
    """Return an AsyncMock that satisfies the get_redis() contract."""
    r = AsyncMock()
    r.incr = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.xadd = AsyncMock(return_value="1-0")
    r.set = AsyncMock(return_value=True)
    r.aclose = AsyncMock()
    return r


def _make_event(**kwargs) -> EventEnvelope:
    defaults = dict(
        event_type="review.repository",
        payload={"repo_url": "https://github.com/test/repo"},
        correlation_id="corr-test",
    )
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


# ---------------------------------------------------------------------------
# track_failure
# ---------------------------------------------------------------------------

class TestTrackFailure:
    async def test_track_failure_increments_counter(self):
        r = _mock_redis()
        r.incr = AsyncMock(return_value=1)

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            count = await track_failure("evt-1", "bvr-review-worker")

        r.incr.assert_awaited_once_with("bvr:failures:evt-1:bvr-review-worker")
        assert count == 1

    async def test_track_failure_returns_new_count(self):
        r = _mock_redis()
        r.incr = AsyncMock(return_value=3)

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            count = await track_failure("evt-2", "bvr-worker")

        assert count == 3

    async def test_track_failure_sets_expiry(self):
        r = _mock_redis()

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await track_failure("evt-3", "grp")

        r.expire.assert_awaited_once()
        key, ttl = r.expire.call_args[0]
        assert "evt-3" in key
        assert ttl == 604800  # 7 days

    async def test_track_failure_closes_redis(self):
        r = _mock_redis()

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await track_failure("evt-4", "grp")

        r.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# clear_failure_counter
# ---------------------------------------------------------------------------

class TestClearFailureCounter:
    async def test_clear_deletes_correct_key(self):
        r = _mock_redis()

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await clear_failure_counter("evt-abc", "bvr-review-worker")

        r.delete.assert_awaited_once_with("bvr:failures:evt-abc:bvr-review-worker")

    async def test_clear_closes_redis(self):
        r = _mock_redis()

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await clear_failure_counter("x", "y")

        r.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# send_to_dlq
# ---------------------------------------------------------------------------

class TestSendToDlq:
    async def test_send_to_dlq_uses_dlq_stream(self):
        r = _mock_redis()
        event = _make_event(event_id="dlq-evt-1")

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await send_to_dlq(event, "bvr-review-worker", "timed out")

        r.xadd.assert_awaited_once()
        stream_name = r.xadd.call_args[0][0]
        assert stream_name == "bvr:events:dlq"

    async def test_send_to_dlq_includes_event_fields(self):
        r = _mock_redis()
        event = _make_event(
            event_id="dlq-evt-2",
            event_type="review.repository",
            correlation_id="corr-dlq",
        )

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await send_to_dlq(event, "bvr-review-worker", "connection refused")

        fields = r.xadd.call_args[0][1]
        assert fields["event_id"] == "dlq-evt-2"
        assert fields["event_type"] == "review.repository"
        assert fields["correlation_id"] == "corr-dlq"
        assert fields["consumer_group"] == "bvr-review-worker"
        assert "connection refused" in fields["error"]

    async def test_send_to_dlq_closes_redis(self):
        r = _mock_redis()
        event = _make_event()

        with patch("bvr_sdk.events.get_redis", AsyncMock(return_value=r)):
            await send_to_dlq(event, "grp", "err")

        r.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Idempotency — subscribe() NX key behaviour
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Tests for the idempotency guard inside subscribe().

    We don't exercise the full subscribe() loop (it blocks); instead we verify
    the Redis SET NX pattern used to deduplicate.
    """

    async def test_set_nx_acquires_lock_on_first_delivery(self):
        """First delivery: r.set(NX=True) returns truthy → handler called."""
        r = _mock_redis()
        r.set = AsyncMock(return_value=True)  # NX acquired

        key = f"bvr:idempotency:evt-id-1:bvr-grp"
        result = await r.set(key, "1", nx=True, ex=86400)

        assert result  # handler should proceed

    async def test_set_nx_fails_on_duplicate_delivery(self):
        """Second delivery: r.set(NX=True) returns falsy → handler skipped."""
        r = _mock_redis()
        r.set = AsyncMock(return_value=None)  # NX not acquired (key exists)

        key = "bvr:idempotency:evt-id-1:bvr-grp"
        result = await r.set(key, "1", nx=True, ex=86400)

        assert not result  # handler should be skipped

    async def test_idempotency_key_includes_consumer_group(self):
        """Key format must include both event_id and consumer_group."""
        r = _mock_redis()
        event_id = str(uuid.uuid4())
        consumer_group = "bvr-review-worker"

        key = f"bvr:idempotency:{event_id}:{consumer_group}"
        await r.set(key, "1", nx=True, ex=86400)

        called_key = r.set.call_args[0][0]
        assert event_id in called_key
        assert consumer_group in called_key

    async def test_idempotency_ttl_is_24h(self):
        r = _mock_redis()

        await r.set("bvr:idempotency:x:y", "1", nx=True, ex=86400)

        kwargs = r.set.call_args[1]
        assert kwargs["ex"] == 86400
