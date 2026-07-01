"""
Tests for bvr_sdk.events — emit_event and subscribe semantics.
Tests for workers.base — consumer group naming.

Redis is fully mocked; no live Redis instance is needed.
conftest.py handles SDK stubs and direct module loading.
"""

import asyncio
import json
import sys
import pytest
from unittest.mock import AsyncMock, patch

# conftest.py has already loaded bvr_sdk.events directly into sys.modules
from bvr_sdk.events import EventEnvelope, emit_event, subscribe  # type: ignore[import]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis_mock(*, xreadgroup_sequences=None):
    """
    Return an AsyncMock that looks like an aioredis client.

    xreadgroup_sequences: list of return values to yield in order.
    After the sequence is consumed, each subsequent call does
    ``await asyncio.sleep(0)`` so the event loop can process
    cancellations and ``asyncio.sleep()`` calls in test helpers.
    Without the yield the while-True loop in subscribe() would
    starve every other coroutine and tests would time out.
    """
    sequences = list(xreadgroup_sequences or [])
    state = {"idx": 0}

    async def _xreadgroup(*args, **kwargs):
        i = state["idx"]
        state["idx"] += 1
        if i < len(sequences):
            return sequences[i]
        await asyncio.sleep(0)  # yield so cancellations can propagate
        return []

    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    r.publish = AsyncMock(return_value=1)
    r.xgroup_create = AsyncMock(return_value=True)
    r.xreadgroup = AsyncMock(side_effect=_xreadgroup)
    r.xack = AsyncMock(return_value=1)
    r.close = AsyncMock()
    return r


def _stream_message(event_type: str, payload: dict, correlation_id: str = "corr-1"):
    """Build a single-message xreadgroup return value."""
    fields = {
        "event_id": "evt-123",
        "event_type": event_type,
        "payload": json.dumps(payload),
        "correlation_id": correlation_id,
        "priority": "normal",
    }
    return [("bvr:events", [("1-0", fields)])]


# ---------------------------------------------------------------------------
# emit_event — stream publishing
# ---------------------------------------------------------------------------

class TestEmitEventStream:
    @pytest.mark.asyncio
    async def test_always_writes_to_stream(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event("review.repository", {"repo_url": "http://x"}, "corr-1")

        r.xadd.assert_awaited_once()
        args = r.xadd.call_args[0]
        assert args[0] == "bvr:events"
        assert args[1]["event_type"] == "review.repository"

    @pytest.mark.asyncio
    async def test_stream_payload_is_json(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event("review.repository", {"repo_url": "http://x"}, "corr-1")

        fields = r.xadd.call_args[0][1]
        # payload must be a JSON string, not a raw dict
        parsed = json.loads(fields["payload"])
        assert parsed == {"repo_url": "http://x"}

    @pytest.mark.asyncio
    async def test_returns_event_envelope(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            result = await emit_event("review.repository", {"k": "v"}, "corr-1")

        assert isinstance(result, EventEnvelope)
        assert result.event_type == "review.repository"
        assert result.correlation_id == "corr-1"

    @pytest.mark.asyncio
    async def test_redis_closed_after_emit(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event("review.repository", {}, "corr-1")

        r.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_closed_even_on_xadd_failure(self):
        r = _make_redis_mock()
        r.xadd = AsyncMock(side_effect=RuntimeError("stream write failed"))
        with patch("bvr_sdk.events.get_redis", return_value=r):
            with pytest.raises(RuntimeError, match="stream write failed"):
                await emit_event("review.repository", {}, "corr-1")

        r.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# emit_event — pub/sub notification for terminal events
# ---------------------------------------------------------------------------

class TestEmitEventPubSub:
    @pytest.mark.asyncio
    async def test_no_pubsub_for_non_terminal_event(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event("review.repository", {"repo_url": "http://x"}, "corr-1")

        r.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pubsub_published_on_completed(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event(
                "review.repository.completed",
                {"score": 80},
                "corr-42",
            )

        r.publish.assert_awaited_once()
        channel, raw = r.publish.call_args[0]
        assert channel == "bvr:webhook:corr-42"
        data = json.loads(raw)
        assert data["status"] == "completed"
        assert data["correlation_id"] == "corr-42"
        assert data["result"] == {"score": 80}

    @pytest.mark.asyncio
    async def test_pubsub_published_on_failed(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event(
                "research.topic.failed",
                {"error": "timeout"},
                "corr-99",
            )

        r.publish.assert_awaited_once()
        channel, raw = r.publish.call_args[0]
        assert channel == "bvr:webhook:corr-99"
        data = json.loads(raw)
        assert data["status"] == "failed"
        assert data["result"] == {"error": "timeout"}

    @pytest.mark.asyncio
    async def test_pubsub_carries_event_type(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event(
                "achieve.resume-optimization.completed",
                {"score_delta": 15},
                "corr-7",
            )

        _, raw = r.publish.call_args[0]
        data = json.loads(raw)
        assert data["event_type"] == "achieve.resume-optimization.completed"

    @pytest.mark.asyncio
    async def test_pubsub_channel_uses_correlation_id(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event(
                "review.repository.completed",
                {},
                "unique-corr-id-xyz",
            )

        channel, _ = r.publish.call_args[0]
        assert channel == "bvr:webhook:unique-corr-id-xyz"

    @pytest.mark.asyncio
    async def test_pubsub_and_stream_both_called_for_completed(self):
        r = _make_redis_mock()
        with patch("bvr_sdk.events.get_redis", return_value=r):
            await emit_event("review.repository.completed", {"score": 90}, "corr-1")

        r.xadd.assert_awaited_once()
        r.publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# subscribe — event type filtering
# ---------------------------------------------------------------------------

async def _run_subscribe_briefly(r, event_types, handler):
    """Run subscribe() as a task and cancel it after a short settle time."""
    with patch("bvr_sdk.events.get_redis", return_value=r):
        task = asyncio.create_task(
            subscribe(
                event_types=event_types,
                consumer_group="bvr-code-analyzer",
                consumer_name="code-analyzer",
                handler=handler,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestSubscribeFiltering:
    @pytest.mark.asyncio
    async def test_matching_event_reaches_handler(self):
        msgs = _stream_message("review.repository", {"repo_url": "http://x"})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])
        handler = AsyncMock()

        await _run_subscribe_briefly(r, ["review.repository"], handler)

        handler.assert_awaited_once()
        assert handler.call_args[0][0].event_type == "review.repository"

    @pytest.mark.asyncio
    async def test_non_matching_event_not_passed_to_handler(self):
        msgs = _stream_message("research.topic", {"topic": "AI"})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])
        handler = AsyncMock()

        await _run_subscribe_briefly(r, ["review.repository"], handler)

        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_matching_event_is_acked(self):
        msgs = _stream_message("research.topic", {"topic": "AI"})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])

        await _run_subscribe_briefly(r, ["review.repository"], AsyncMock())

        r.xack.assert_awaited_once_with("bvr:events", "bvr-code-analyzer", "1-0")

    @pytest.mark.asyncio
    async def test_matching_event_acked_after_handler_success(self):
        msgs = _stream_message("review.repository", {"repo_url": "http://x"})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])
        handler = AsyncMock()

        await _run_subscribe_briefly(r, ["review.repository"], handler)

        r.xack.assert_awaited_once_with("bvr:events", "bvr-code-analyzer", "1-0")

    @pytest.mark.asyncio
    async def test_handler_failure_still_acks(self):
        """
        Even when the handler raises, the message must be ACK'd.
        Event status is tracked in postgres; leaving PEL entries indefinitely
        causes unbounded accumulation on pod restarts.
        BaseWorker._handle_event catches all exceptions internally so this
        path covers unexpected lower-level failures (e.g. asyncio.CancelledError
        reaching the subscribe loop after a SIGTERM).
        """
        msgs = _stream_message("review.repository", {"repo_url": "http://x"})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])

        async def failing_handler(event):
            raise ValueError("handler blew up")

        await _run_subscribe_briefly(r, ["review.repository"], failing_handler)

        r.xack.assert_awaited_once_with("bvr:events", "bvr-code-analyzer", "1-0")

    @pytest.mark.asyncio
    async def test_completion_event_discarded_not_passed_to_handler(self):
        """
        .completed events emitted by other workers must be discarded — they are
        not in any worker's capabilities list and must not reach handle().
        """
        msgs = _stream_message("review.repository.completed", {"score": 90})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])
        handler = AsyncMock()

        await _run_subscribe_briefly(r, ["review.repository"], handler)

        handler.assert_not_awaited()
        r.xack.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consumer_group_passed_to_xgroup_create(self):
        r = _make_redis_mock()

        await _run_subscribe_briefly(r, ["review.repository"], AsyncMock())

        r.xgroup_create.assert_awaited_once_with(
            "bvr:events", "bvr-code-analyzer", id="0", mkstream=True
        )

    @pytest.mark.asyncio
    async def test_multiple_event_types_all_match(self):
        """A worker with multiple capabilities should handle all of them."""
        msgs = _stream_message("scan_repo", {"repo_url": "http://x"})
        r = _make_redis_mock(xreadgroup_sequences=[msgs])
        handler = AsyncMock()

        await _run_subscribe_briefly(
            r, ["review.repository", "analyze_code", "scan_repo"], handler
        )

        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_only_matching_type_calls_handler_among_mixed_messages(self):
        """
        Two messages arrive: one matching, one not.
        Only the matching one must reach the handler.
        """
        matching = _stream_message("review.repository", {"repo_url": "http://x"})
        non_matching = _stream_message("research.topic", {"topic": "AI"})
        r = _make_redis_mock(xreadgroup_sequences=[matching, non_matching])
        handler = AsyncMock()

        await _run_subscribe_briefly(r, ["review.repository"], handler)

        assert handler.await_count == 1
        assert handler.call_args[0][0].event_type == "review.repository"


# ---------------------------------------------------------------------------
# Consumer group naming (via BaseWorker)
# ---------------------------------------------------------------------------

class TestBaseWorkerConsumerGroup:
    @pytest.mark.asyncio
    async def test_worker_uses_type_scoped_consumer_group(self):
        """
        BaseWorker.start() must pass consumer_group='bvr-{worker_id}'
        to subscribe(), not the old hardcoded 'bvr-workers'.
        """
        subscribe_calls = []

        async def fake_subscribe(**kwargs):
            subscribe_calls.append(kwargs)

        async def fake_register(**kwargs):
            return {"status": "registered"}

        with patch("workers.base.subscribe", side_effect=fake_subscribe), \
             patch("workers.base.register_worker", side_effect=fake_register):
            from workers.base import BaseWorker  # noqa: PLC0415

            class _TestWorker(BaseWorker):
                worker_id = "code-analyzer"
                capabilities = ["review.repository"]

                async def handle(self, event):
                    return {}

            await _TestWorker().start()

        assert len(subscribe_calls) == 1
        assert subscribe_calls[0]["consumer_group"] == "bvr-code-analyzer"
        assert subscribe_calls[0]["consumer_group"] != "bvr-workers"

    @pytest.mark.asyncio
    async def test_different_worker_types_use_different_groups(self):
        groups = []

        async def fake_subscribe(**kwargs):
            groups.append(kwargs["consumer_group"])

        async def fake_register(**kwargs):
            return {}

        with patch("workers.base.subscribe", side_effect=fake_subscribe), \
             patch("workers.base.register_worker", side_effect=fake_register):
            from workers.base import BaseWorker  # noqa: PLC0415

            class _ReviewWorker(BaseWorker):
                worker_id = "code-analyzer"
                capabilities = ["review.repository"]
                async def handle(self, event): return {}

            class _ResearchWorker(BaseWorker):
                worker_id = "research-worker"
                capabilities = ["research.topic"]
                async def handle(self, event): return {}

            await _ReviewWorker().start()
            await _ResearchWorker().start()

        assert "bvr-code-analyzer" in groups
        assert "bvr-research-worker" in groups
        assert len(set(groups)) == 2

    @pytest.mark.asyncio
    async def test_consumer_group_not_bvr_workers(self):
        """Regression: the old hardcoded value must not appear."""
        groups = []

        async def fake_subscribe(**kwargs):
            groups.append(kwargs["consumer_group"])

        async def fake_register(**kwargs):
            return {}

        with patch("workers.base.subscribe", side_effect=fake_subscribe), \
             patch("workers.base.register_worker", side_effect=fake_register):
            from workers.base import BaseWorker  # noqa: PLC0415

            class _W(BaseWorker):
                worker_id = "achieve-worker"
                capabilities = ["achieve.resume-optimization"]
                async def handle(self, event): return {}

            await _W().start()

        assert "bvr-workers" not in groups
