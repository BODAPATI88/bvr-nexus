"""
Tests for workers.research_worker.ResearchWorker.handle().
All external I/O is mocked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bvr_sdk.events import EventEnvelope  # type: ignore[import]
from workers.research_worker import ResearchWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kwargs) -> EventEnvelope:
    defaults = dict(
        event_type="research.topic",
        payload={"topic": "GraphQL vs REST for microservices", "depth": "standard"},
        correlation_id="corr-research-1",
    )
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


def _make_matcher_stub():
    """Return a stub CapabilityMatcher."""
    provider = MagicMock()
    provider.id = "kimi_summarize"
    matcher = MagicMock()
    matcher.resolve.return_value = provider
    matcher.get_provider_config.return_value = {}
    return matcher


def _ai_response(text: str, model: str = "kimi-moonshot", cost: float = 0.0005) -> dict:
    return {"text": text, "model_used": model, "cost_usd": cost}


_DEFAULT_SUMMARY = (
    "## Key Findings\nREST is simpler for CRUD. GraphQL shines for complex queries.\n"
    "## Trade-offs\nREST: simpler tooling. GraphQL: flexible.\n"
    "## Recommendation\nUse REST for simple APIs.\n"
    "## Confidence: 85%"
)
_DEFAULT_AI = _ai_response(_DEFAULT_SUMMARY)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestResearchWorkerHandle:
    @pytest.mark.asyncio
    async def test_returns_summary_and_status(self):
        """Happy path: result contains summary, artifact_url, and status == completed."""
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call",
            AsyncMock(return_value=_DEFAULT_AI),
        ), patch(
            "workers.research_worker.upload_artifact",
            AsyncMock(return_value="http://minio/research/corr-research-1/summary.md"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["summary"] == _DEFAULT_SUMMARY
        assert result["artifact_url"] == "http://minio/research/corr-research-1/summary.md"
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_confidence_extracted_from_summary(self):
        """LLM text containing 'Confidence: 85%' → confidence == '85%'."""
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call",
            AsyncMock(return_value=_DEFAULT_AI),
        ), patch(
            "workers.research_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["confidence"] == "85%"

    @pytest.mark.asyncio
    async def test_default_confidence_when_no_match(self):
        """LLM text without confidence pattern → confidence == 'Unknown'."""
        no_conf_response = _ai_response("Summary without any confidence marker here.")
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call",
            AsyncMock(return_value=no_conf_response),
        ), patch(
            "workers.research_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            result = await worker.handle(_make_event())

        assert result["confidence"] == "Unknown"

    @pytest.mark.asyncio
    async def test_upload_called_with_correlation_id(self):
        """Artifact path must contain event.correlation_id and end with '.md'."""
        upload_mock = AsyncMock(return_value="http://minio/research/corr-research-42/summary.md")
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call",
            AsyncMock(return_value=_DEFAULT_AI),
        ), patch(
            "workers.research_worker.upload_artifact", upload_mock
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            await worker.handle(_make_event(correlation_id="corr-research-42"))

        upload_mock.assert_awaited_once()
        call_kw = upload_mock.call_args[1]
        path = call_kw.get("path") or upload_mock.call_args[0][1]
        assert "corr-research-42" in path
        assert path.endswith(".md")

    @pytest.mark.asyncio
    async def test_ai_gateway_uses_summarization_capability(self):
        """ai_gateway_call must be invoked with capability='summarization'."""
        ai_call = AsyncMock(return_value=_DEFAULT_AI)
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call", ai_call
        ), patch(
            "workers.research_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            await worker.handle(_make_event())

        ai_call.assert_awaited_once()
        assert ai_call.call_args[1]["capability"] == "summarization"

    @pytest.mark.asyncio
    async def test_missing_topic_raises(self):
        """Payload without 'topic' key → KeyError (research_worker does payload['topic'])."""
        event = _make_event(payload={"depth": "deep"})  # no topic key
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call",
            AsyncMock(return_value=_DEFAULT_AI),
        ), patch(
            "workers.research_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            with pytest.raises(KeyError):
                await worker.handle(event)

    @pytest.mark.asyncio
    async def test_depth_defaults_to_standard(self):
        """Payload without 'depth' → worker runs without error (uses .get('depth', 'standard'))."""
        event = _make_event(payload={"topic": "Kubernetes vs Docker Swarm"})  # no depth
        worker = ResearchWorker()

        with patch(
            "workers.research_worker.ai_gateway_call",
            AsyncMock(return_value=_DEFAULT_AI),
        ), patch(
            "workers.research_worker.upload_artifact",
            AsyncMock(return_value="http://minio/x"),
        ), patch(
            "bvr_sdk.get_matcher", return_value=_make_matcher_stub()
        ):
            # Should not raise — research_worker uses .get("depth", "standard")
            result = await worker.handle(event)

        assert result["status"] == "completed"
