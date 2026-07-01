"""
Tests for workers.review_worker.ReviewWorker.handle().

All external I/O is mocked:
  - bvr_sdk.ai_gateway_call
  - bvr_sdk.upload_artifact
  - bvr_sdk.get_matcher → CapabilityMatcher stub
  - ReviewWorker.registry property → PluginRegistry stub
  - SLACK_WEBHOOK_URL env var for best-effort Slack path
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from bvr_sdk.events import EventEnvelope  # type: ignore[import]
from workers.review_worker import ReviewWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs) -> EventEnvelope:
    defaults = dict(
        event_type="review.repository",
        payload={"repo_url": "https://github.com/test/repo", "branch": "main"},
        correlation_id="corr-review-1",
    )
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


def _make_matcher_stub():
    """Return a stub CapabilityMatcher."""
    provider = MagicMock()
    provider.id = "github_clone"
    provider.plugin_id = "code/github"
    matcher = MagicMock()
    matcher.resolve.return_value = provider
    matcher.get_provider_config.return_value = {"token": "fake-token"}
    return matcher


def _make_registry_stub(clone_files=None, num_files=15):
    """Return a stub PluginRegistry."""
    if clone_files is None:
        clone_files = [f"file_{i}.py" for i in range(num_files)]
    clone_result = {"directory": "/tmp/cloned", "files": clone_files}
    registry = MagicMock()
    registry.execute = AsyncMock(return_value=clone_result)
    return registry


_DEFAULT_AI = {
    "text": "Architecture looks solid. Score: 82/100",
    "model_used": "claude-3",
    "cost_usd": 0.0012,
    "tokens_input": 200,
    "tokens_output": 300,
}


# ---------------------------------------------------------------------------
# Full-flow tests
# ---------------------------------------------------------------------------

class TestReviewWorkerHandle:
    @pytest.mark.asyncio
    async def test_returns_score_and_status(self):
        registry = _make_registry_stub()
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value=_DEFAULT_AI)), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://minio/r.md")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            result = await worker.handle(_make_event())

        assert result["score"] == 82
        assert result["status"] == "completed"
        assert result["artifact_url"] == "http://minio/r.md"

    @pytest.mark.asyncio
    async def test_score_extracted_from_llm_text(self):
        registry = _make_registry_stub()
        ai_result = {**_DEFAULT_AI, "text": "This repo scores 67/100 overall."}
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value=ai_result)), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            result = await worker.handle(_make_event())

        assert result["score"] == 67

    @pytest.mark.asyncio
    async def test_default_score_when_no_number_in_text(self):
        registry = _make_registry_stub()
        ai_result = {**_DEFAULT_AI, "text": "Looks reasonable."}
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value=ai_result)), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            result = await worker.handle(_make_event())

        assert result["score"] == 75  # hardcoded default

    @pytest.mark.asyncio
    async def test_files_analyzed_count_is_correct(self):
        registry = _make_registry_stub(num_files=42)
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value=_DEFAULT_AI)), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            result = await worker.handle(_make_event())

        assert result["files_analyzed"] == 42

    @pytest.mark.asyncio
    async def test_ai_gateway_call_uses_code_analysis_capability(self):
        registry = _make_registry_stub()
        ai_call = AsyncMock(return_value={**_DEFAULT_AI, "text": "ok"})
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", ai_call), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            await worker.handle(_make_event())

        ai_call.assert_awaited_once()
        assert ai_call.call_args[1]["capability"] == "code_analysis"

    @pytest.mark.asyncio
    async def test_upload_artifact_called_with_correct_path(self):
        registry = _make_registry_stub()
        upload = AsyncMock(return_value="http://minio/reports/corr-review-1/review.md")
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value=_DEFAULT_AI)), \
             patch("workers.review_worker.upload_artifact", upload), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            await worker.handle(_make_event(correlation_id="corr-review-1"))

        upload.assert_awaited_once()
        call_kw = upload.call_args[1]
        path = call_kw.get("path") or upload.call_args[0][1]
        assert "corr-review-1" in path
        assert path.endswith(".md")


# ---------------------------------------------------------------------------
# Missing payload field
# ---------------------------------------------------------------------------

class TestReviewWorkerValidation:
    @pytest.mark.asyncio
    async def test_missing_repo_url_raises(self):
        event = _make_event(payload={})  # no repo_url

        worker = ReviewWorker()
        with pytest.raises(KeyError):
            await worker.handle(event)


# ---------------------------------------------------------------------------
# Slack — best-effort (non-fatal)
# ---------------------------------------------------------------------------

class TestReviewWorkerSlack:
    @pytest.mark.asyncio
    async def test_slack_not_called_when_url_is_placeholder(self, monkeypatch):
        monkeypatch.setenv(
            "SLACK_WEBHOOK_URL",
            "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
        )
        execute_spy = AsyncMock(return_value={"directory": "/tmp/r", "files": ["f.py"]})
        registry = MagicMock()
        registry.execute = execute_spy
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value={**_DEFAULT_AI, "text": "ok"})), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            await worker.handle(_make_event())

        slack_calls = [c for c in execute_spy.call_args_list if c[0][0] == "productivity/slack"]
        assert len(slack_calls) == 0

    @pytest.mark.asyncio
    async def test_slack_failure_does_not_fail_review(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/REAL/HOOK/URL")
        execute_spy = AsyncMock(side_effect=[
            {"directory": "/tmp/r", "files": ["f.py"]},  # clone succeeds
            Exception("Slack 500"),                        # Slack fails
        ])
        registry = MagicMock()
        registry.execute = execute_spy
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value={**_DEFAULT_AI, "text": "ok"})), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            result = await worker.handle(_make_event())

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_slack_not_called_when_env_var_empty(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
        execute_spy = AsyncMock(return_value={"directory": "/tmp/r", "files": ["f.py"]})
        registry = MagicMock()
        registry.execute = execute_spy
        worker = ReviewWorker()

        with patch("workers.review_worker.ai_gateway_call", AsyncMock(return_value={**_DEFAULT_AI, "text": "ok"})), \
             patch("workers.review_worker.upload_artifact", AsyncMock(return_value="http://x")), \
             patch("bvr_sdk.get_matcher", return_value=_make_matcher_stub()), \
             patch.object(ReviewWorker, "registry", new_callable=PropertyMock, return_value=registry):
            await worker.handle(_make_event())

        slack_calls = [c for c in execute_spy.call_args_list if c[0][0] == "productivity/slack"]
        assert len(slack_calls) == 0
