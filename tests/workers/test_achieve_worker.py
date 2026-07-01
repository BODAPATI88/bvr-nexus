"""
Tests for workers.achieve_worker.ResumeOptimizerWorker.handle().
All external I/O is mocked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bvr_sdk.events import EventEnvelope  # type: ignore[import]
from workers.achieve_worker import ResumeOptimizerWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs) -> EventEnvelope:
    defaults = dict(
        event_type="achieve.resume-optimization",
        payload={
            "resume_content": "Experienced engineer with 5 years in Python.",
            "target_role": "Senior Software Engineer",
        },
        correlation_id="corr-achieve-1",
    )
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


def _make_matcher_stub():
    """Return a stub CapabilityMatcher."""
    provider = MagicMock()
    provider.id = "claude_analysis"
    matcher = MagicMock()
    matcher.resolve.return_value = provider
    matcher.get_provider_config.return_value = {}
    return matcher


def _ai_response(text: str, model: str = "claude-3", cost: float = 0.001) -> dict:
    return {"text": text, "model_used": model, "cost_usd": cost}


# Two-call default responses used across multiple tests
_ANALYSIS_RESPONSE = _ai_response("The resume is good. ATS score: 72/100")
_OPTIMIZE_RESPONSE = _ai_response("Improved resume. New rating: 88/100", cost=0.002)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestResumeOptimizerWorkerHandle:
    @pytest.mark.asyncio
    async def test_returns_scores_and_status(self):
        """Happy path: result dict contains required keys with correct types."""
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[_ANALYSIS_RESPONSE, _OPTIMIZE_RESPONSE]),
        ), patch(
            "workers.achieve_worker.upload_artifact",
            AsyncMock(return_value="http://minio/resumes/corr-achieve-1/optimized.md"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert "initial_score" in result
        assert "optimized_score" in result
        assert "score_delta" in result
        assert "artifact_url" in result
        assert result["status"] == "completed"
        assert isinstance(result["initial_score"], int)
        assert isinstance(result["optimized_score"], int)

    @pytest.mark.asyncio
    async def test_score_extracted_from_analysis_text(self):
        """LLM text 'ATS score: 65/100' → initial_score == 65."""
        analysis = _ai_response("Keywords look weak. ATS score: 65/100")
        optimized = _ai_response("Better now. rating: 80/100")
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[analysis, optimized]),
        ), patch(
            "workers.achieve_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["initial_score"] == 65

    @pytest.mark.asyncio
    async def test_score_extracted_from_optimized_text(self):
        """Optimized LLM text 'rating: 88/100' → optimized_score == 88."""
        analysis = _ai_response("Looks good. Score: 70/100")
        optimized = _ai_response("Much improved. rating: 88/100")
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[analysis, optimized]),
        ), patch(
            "workers.achieve_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["optimized_score"] == 88

    @pytest.mark.asyncio
    async def test_default_score_when_no_match(self):
        """LLM text with no score pattern → score == 70 (hardcoded default)."""
        no_score_response = _ai_response("The resume looks reasonable but needs work.")
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[no_score_response, no_score_response]),
        ), patch(
            "workers.achieve_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["initial_score"] == 70
        assert result["optimized_score"] == 70

    @pytest.mark.asyncio
    async def test_score_delta_is_optimized_minus_initial(self):
        """score_delta == optimized_score - initial_score."""
        analysis = _ai_response("Score: 60/100")
        optimized = _ai_response("Rating: 85/100")
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[analysis, optimized]),
        ), patch(
            "workers.achieve_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["score_delta"] == result["optimized_score"] - result["initial_score"]
        assert result["score_delta"] == 25

    @pytest.mark.asyncio
    async def test_upload_artifact_called_with_correlation_id(self):
        """Artifact path must contain event.correlation_id."""
        upload_mock = AsyncMock(return_value="http://minio/resumes/corr-achieve-99/optimized.md")
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[_ANALYSIS_RESPONSE, _OPTIMIZE_RESPONSE]),
        ), patch(
            "workers.achieve_worker.upload_artifact", upload_mock
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            await worker.handle(_make_event(correlation_id="corr-achieve-99"))

        upload_mock.assert_awaited_once()
        call_kw = upload_mock.call_args[1]
        path = call_kw.get("path") or upload_mock.call_args[0][1]
        assert "corr-achieve-99" in path

    @pytest.mark.asyncio
    async def test_missing_resume_content_uses_empty_string(self):
        """Payload without resume_content → worker handles it without KeyError."""
        event = _make_event(
            payload={"target_role": "Data Scientist"}  # no resume_content key
        )
        worker = ResumeOptimizerWorker()

        with patch(
            "workers.achieve_worker.ai_gateway_call",
            AsyncMock(side_effect=[_ANALYSIS_RESPONSE, _OPTIMIZE_RESPONSE]),
        ), patch(
            "workers.achieve_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            # Should not raise — achieve_worker uses .get("resume_content", "")
            result = await worker.handle(event)

        assert result["status"] == "completed"
