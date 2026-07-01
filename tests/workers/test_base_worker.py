"""
Tests for workers.base — BaseWorker._handle_event and _post_result.

SDK is fully stubbed via conftest.py. No live Redis or HTTP needed.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from bvr_sdk.events import EventEnvelope  # type: ignore[import]
from workers.base import BaseWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs) -> EventEnvelope:
    defaults = dict(
        event_type="review.repository",
        payload={"repo_url": "https://github.com/test/repo"},
        correlation_id="corr-test",
    )
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


class _ConcreteWorker(BaseWorker):
    """Minimal concrete subclass for testing BaseWorker internals."""
    worker_id = "test-worker"

    async def handle(self, event):
        return {}

    @classmethod
    def with_result(cls, result=None, side_effect=None):
        """Factory — returns a worker whose handle() is an AsyncMock."""
        worker = cls()
        if side_effect is not None:
            worker.handle = AsyncMock(side_effect=side_effect)
        else:
            worker.handle = AsyncMock(return_value=result if result is not None else {"score": 80})
        return worker


# ---------------------------------------------------------------------------
# _handle_event — success path
# ---------------------------------------------------------------------------

class TestHandleEventSuccess:
    @pytest.mark.asyncio
    async def test_check_policy_called_with_event_fields(self):
        event = _make_event(event_type="review.repository", user_id="user-42")
        policy_mock = AsyncMock(return_value=True)

        worker = _ConcreteWorker.with_result(result={"score": 80})
        with patch("workers.base.check_policy", policy_mock), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        policy_mock.assert_awaited_once()
        args = policy_mock.call_args[0]
        assert args[0] == "bvr.allow"
        assert args[1]["action"] == "review.repository"

    @pytest.mark.asyncio
    async def test_handle_called_with_event(self):
        event = _make_event()
        worker = _ConcreteWorker.with_result(result={"score": 80})

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        worker.handle.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_post_result_called_with_completed_status(self):
        event = _make_event()
        post_mock = AsyncMock()
        worker = _ConcreteWorker.with_result(result={"score": 80})

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", post_mock):
            await worker._handle_event(event)

        assert post_mock.await_count == 1
        call_args = post_mock.call_args[0]
        assert call_args[1] == "completed"

    @pytest.mark.asyncio
    async def test_artifact_url_extracted_and_not_in_result_body(self):
        event = _make_event()
        post_mock = AsyncMock()
        worker = _ConcreteWorker.with_result(result={
            "score": 90,
            "artifact_url": "http://minio/reports/x.md"
        })

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", post_mock):
            await worker._handle_event(event)

        event_id, status, result, artifact_urls = post_mock.call_args[0]
        assert "artifact_url" not in result
        assert artifact_urls == ["http://minio/reports/x.md"]

    @pytest.mark.asyncio
    async def test_completion_event_emitted_after_success(self):
        event = _make_event(event_type="review.repository", correlation_id="corr-XY")
        emit_mock = AsyncMock(return_value=MagicMock())
        worker = _ConcreteWorker.with_result(result={"score": 80})

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", emit_mock), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        emit_mock.assert_awaited_once()
        kwargs = emit_mock.call_args[1]
        assert kwargs["event_type"] == "review.repository.completed"
        assert kwargs["correlation_id"] == "corr-XY"


# ---------------------------------------------------------------------------
# _handle_event — failure path
# ---------------------------------------------------------------------------

class TestHandleEventFailure:
    @pytest.mark.asyncio
    async def test_handle_exception_posts_failed_status(self):
        event = _make_event()
        post_mock = AsyncMock()
        worker = _ConcreteWorker.with_result(side_effect=ValueError("something broke"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", post_mock):
            await worker._handle_event(event)  # must not re-raise

        assert post_mock.await_count == 1
        _, status, result = post_mock.call_args[0][:3]
        assert status == "failed"
        assert "something broke" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_exception_does_not_propagate(self):
        event = _make_event()
        worker = _ConcreteWorker.with_result(side_effect=RuntimeError("boom"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)  # must complete without raising

    @pytest.mark.asyncio
    async def test_policy_denial_does_not_call_handle(self):
        event = _make_event()
        worker = _ConcreteWorker.with_result(result={})

        with patch("workers.base.check_policy", AsyncMock(side_effect=PermissionError("denied"))), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        worker.handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_completion_event_emitted_on_failure(self):
        """On handle() failure, no .completed event must reach the stream."""
        event = _make_event()
        emit_mock = AsyncMock(return_value=MagicMock())
        worker = _ConcreteWorker.with_result(side_effect=ValueError("fail"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", emit_mock), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        emit_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_event — DLQ tracking
# ---------------------------------------------------------------------------

class TestDlqTracking:
    @pytest.mark.asyncio
    async def test_failure_counter_incremented_on_exception(self):
        event = _make_event()
        track_mock = AsyncMock(return_value=1)
        clear_mock = AsyncMock()
        dlq_mock = AsyncMock()
        worker = _ConcreteWorker.with_result(side_effect=RuntimeError("boom"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch("workers.base.track_failure", track_mock), \
             patch("workers.base.clear_failure_counter", clear_mock), \
             patch("workers.base.send_to_dlq", dlq_mock), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        track_mock.assert_awaited_once()
        clear_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_counter_cleared_on_success(self):
        event = _make_event()
        clear_mock = AsyncMock()
        track_mock = AsyncMock(return_value=0)
        worker = _ConcreteWorker.with_result(result={"score": 80})

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch("workers.base.track_failure", track_mock), \
             patch("workers.base.clear_failure_counter", clear_mock), \
             patch("workers.base.send_to_dlq", AsyncMock()), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        clear_mock.assert_awaited_once()
        track_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_to_dlq_called_when_max_retries_reached(self):
        from workers.base import MAX_RETRIES
        event = _make_event()
        dlq_mock = AsyncMock()
        # track_failure returns MAX_RETRIES → triggers DLQ
        track_mock = AsyncMock(return_value=MAX_RETRIES)
        worker = _ConcreteWorker.with_result(side_effect=ValueError("persistent error"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch("workers.base.track_failure", track_mock), \
             patch("workers.base.clear_failure_counter", AsyncMock()), \
             patch("workers.base.send_to_dlq", dlq_mock), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        dlq_mock.assert_awaited_once()
        args = dlq_mock.call_args[0]
        assert args[0] == event  # first arg is the event
        assert "persistent error" in args[2]  # third arg is error string

    @pytest.mark.asyncio
    async def test_dlq_not_called_below_max_retries(self):
        from workers.base import MAX_RETRIES
        event = _make_event()
        dlq_mock = AsyncMock()
        # Returns one below threshold
        track_mock = AsyncMock(return_value=MAX_RETRIES - 1)
        worker = _ConcreteWorker.with_result(side_effect=ValueError("transient"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch("workers.base.track_failure", track_mock), \
             patch("workers.base.clear_failure_counter", AsyncMock()), \
             patch("workers.base.send_to_dlq", dlq_mock), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        dlq_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_consumer_group_derived_from_worker_id(self):
        event = _make_event()
        track_mock = AsyncMock(return_value=1)
        worker = _ConcreteWorker.with_result(side_effect=ValueError("fail"))

        with patch("workers.base.check_policy", AsyncMock(return_value=True)), \
             patch("workers.base.emit_event", AsyncMock(return_value=MagicMock())), \
             patch("workers.base.track_failure", track_mock), \
             patch("workers.base.clear_failure_counter", AsyncMock()), \
             patch("workers.base.send_to_dlq", AsyncMock()), \
             patch.object(worker, "_post_result", AsyncMock()):
            await worker._handle_event(event)

        args = track_mock.call_args[0]
        assert args[1] == f"bvr-{worker.worker_id}"


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_start_passes_shutdown_event_to_subscribe(self):
        """subscribe() must receive a shutdown_event keyword argument."""
        import asyncio as _asyncio
        from unittest.mock import AsyncMock as _AM, patch as _patch

        worker = _ConcreteWorker()
        subscribe_mock = _AM()
        register_mock = _AM()

        with _patch("workers.base.subscribe", subscribe_mock), \
             _patch("workers.base.register_worker", register_mock):
            await worker.start()

        subscribe_mock.assert_awaited_once()
        kwargs = subscribe_mock.call_args[1]
        assert "shutdown_event" in kwargs
        assert isinstance(kwargs["shutdown_event"], _asyncio.Event)

    @pytest.mark.asyncio
    async def test_start_registers_worker_before_subscribing(self):
        import asyncio as _asyncio

        worker = _ConcreteWorker()
        call_order = []
        register_mock = AsyncMock(side_effect=lambda **kw: call_order.append("register"))
        subscribe_mock = AsyncMock(side_effect=lambda **kw: call_order.append("subscribe"))

        with patch("workers.base.subscribe", subscribe_mock), \
             patch("workers.base.register_worker", register_mock):
            await worker.start()

        assert call_order == ["register", "subscribe"]


# ---------------------------------------------------------------------------
# _post_result — error isolation
# ---------------------------------------------------------------------------

class TestPostResult:
    @pytest.mark.asyncio
    async def test_post_result_swallows_http_errors(self):
        """HTTP failure in _post_result must not propagate to caller."""
        worker = _ConcreteWorker.with_result()

        with patch("workers.base.httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_ctx

            # Must not raise
            await worker._post_result("evt-1", "completed", {"score": 80})

    @pytest.mark.asyncio
    async def test_post_result_sends_correct_payload(self):
        worker = _ConcreteWorker.with_result()
        post_spy = AsyncMock(return_value=MagicMock(status_code=200))

        with patch("workers.base.httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.post = post_spy
            mock_client_cls.return_value = mock_ctx

            await worker._post_result("evt-abc", "completed", {"score": 95}, ["http://minio/x"])

        post_spy.assert_awaited_once()
        body = post_spy.call_args[1]["json"]
        assert body["event_id"] == "evt-abc"
        assert body["status"] == "completed"
        assert body["result"] == {"score": 95}
        assert body["artifact_urls"] == ["http://minio/x"]
