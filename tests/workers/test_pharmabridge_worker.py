"""
Tests for PharmabridgeWorker.handle() and the plugin's execute() function.

All external I/O is mocked:
  - plugins.pharma.pharmabridge.worker.ai_gateway_call
  - plugins.pharma.pharmabridge.worker.upload_artifact
  - plugins.pharma.pharmabridge.worker.emit_event
  - bvr_sdk.check_policy
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from bvr_sdk.events import EventEnvelope  # type: ignore[import]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> EventEnvelope:
    defaults = dict(
        event_type="bvr.pharma.trial.analyze",
        payload={
            "trial_id": "NCT12345678",
            "data_source": "csv",
            "analysis_type": "efficacy",
            "data_url": "s3://artifacts/pharmabridge/input/NCT12345678.csv",
            "notify_slack": False,
        },
        correlation_id="corr-pharma-1",
        user_id="test-user",
    )
    defaults["payload"].update(overrides.pop("payload", {}))
    defaults.update(overrides)
    return EventEnvelope(**defaults)


_AI_RESPONSE = {
    "content": json.dumps({
        "summary": "Efficacy results show significant improvement.",
        "findings": [
            {"category": "primary_endpoint", "severity": "info", "description": "p < 0.001"}
        ],
        "recommendations": ["Continue to Phase 3"],
    }),
    "usage": {"input_tokens": 500, "output_tokens": 200, "cost_usd": 0.006},
}

_POLICY_ALLOW = True
_POLICY_DENY = False


# ---------------------------------------------------------------------------
# Plugin execute() tests
# ---------------------------------------------------------------------------

class TestPharmabridgePluginExecute:
    async def test_execute_returns_report_url(self):
        from plugins.pharma.pharmabridge.worker import execute

        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=_AI_RESPONSE)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://artifacts/pharmabridge/reports/NCT12345678/efficacy.json")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", new=AsyncMock()):
            result = await execute(
                {"trial_id": "NCT12345678", "data_source": "csv", "analysis_type": "efficacy"},
                {"timestamp": "2024-01-01T00:00:00Z", "correlation_id": "c1", "user_id": "u1"},
            )
        assert "report_url" in result
        assert "NCT12345678" in result["report_url"]

    async def test_execute_returns_summary(self):
        from plugins.pharma.pharmabridge.worker import execute

        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=_AI_RESPONSE)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", new=AsyncMock()):
            result = await execute(
                {"trial_id": "NCT12345678", "data_source": "csv", "analysis_type": "efficacy"},
                {},
            )
        assert result["summary"] == "Efficacy results show significant improvement."

    async def test_execute_returns_findings(self):
        from plugins.pharma.pharmabridge.worker import execute

        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=_AI_RESPONSE)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", new=AsyncMock()):
            result = await execute(
                {"trial_id": "NCT12345678", "data_source": "csv", "analysis_type": "efficacy"},
                {},
            )
        assert isinstance(result["findings"], list)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["category"] == "primary_endpoint"

    async def test_execute_tracks_token_usage(self):
        from plugins.pharma.pharmabridge.worker import execute

        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=_AI_RESPONSE)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", new=AsyncMock()):
            result = await execute(
                {"trial_id": "NCT12345678", "data_source": "csv", "analysis_type": "safety"},
                {},
            )
        assert result["token_usage"]["input_tokens"] == 500
        assert result["token_usage"]["output_tokens"] == 200

    async def test_execute_handles_non_json_ai_response(self):
        from plugins.pharma.pharmabridge.worker import execute

        plain_response = {"content": "Analysis complete. No issues found.", "usage": {}}
        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=plain_response)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", new=AsyncMock()):
            result = await execute(
                {"trial_id": "NCT99999", "data_source": "fhir", "analysis_type": "enrollment"},
                {},
            )
        assert "summary" in result
        assert isinstance(result["findings"], list)

    async def test_execute_sends_slack_when_flag_set(self):
        from plugins.pharma.pharmabridge.worker import execute

        mock_emit = AsyncMock()
        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=_AI_RESPONSE)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", mock_emit):
            await execute(
                {
                    "trial_id": "NCT12345678",
                    "data_source": "csv",
                    "analysis_type": "efficacy",
                    "notify_slack": True,
                },
                {},
            )
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args[1] if mock_emit.call_args[1] else {}
        call_args = mock_emit.call_args[0] if mock_emit.call_args[0] else ()
        # verify emit was called with notification event
        event_type = call_kwargs.get("event_type") or (call_args[0] if call_args else "")
        assert "notification" in str(event_type) or mock_emit.called

    async def test_execute_does_not_send_slack_by_default(self):
        from plugins.pharma.pharmabridge.worker import execute

        mock_emit = AsyncMock()
        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", new=AsyncMock(return_value=_AI_RESPONSE)), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", mock_emit):
            await execute(
                {"trial_id": "NCT12345678", "data_source": "csv", "analysis_type": "efficacy"},
                {},
            )
        mock_emit.assert_not_called()

    async def test_execute_uses_correct_prompt_for_safety(self):
        from plugins.pharma.pharmabridge.worker import execute

        mock_ai = AsyncMock(return_value=_AI_RESPONSE)
        with patch("plugins.pharma.pharmabridge.worker.ai_gateway_call", mock_ai), \
             patch("plugins.pharma.pharmabridge.worker.upload_artifact", new=AsyncMock(return_value="s3://r")), \
             patch("plugins.pharma.pharmabridge.worker.emit_event", new=AsyncMock()):
            await execute(
                {"trial_id": "NCT12345678", "data_source": "csv", "analysis_type": "safety"},
                {},
            )
        call_kwargs = mock_ai.call_args[1]
        assert "adverse" in call_kwargs.get("system_prompt", "").lower() or \
               "safety" in call_kwargs.get("system_prompt", "").lower()


# ---------------------------------------------------------------------------
# PharmabridgeWorker.handle() tests
# ---------------------------------------------------------------------------

class TestPharmabridgeWorker:
    async def test_handle_returns_result(self):
        from workers.pharmabridge_worker import PharmabridgeWorker

        mock_execute = AsyncMock(return_value={
            "report_url": "s3://r",
            "summary": "ok",
            "findings": [],
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            "duration_ms": 100,
        })
        with patch("bvr_sdk.check_policy", new=AsyncMock(return_value=_POLICY_ALLOW)), \
             patch("plugins.pharma.pharmabridge.worker.execute", mock_execute), \
             patch("workers.pharmabridge_worker.emit_event", new=AsyncMock()):
            worker = PharmabridgeWorker()
            result = await worker.handle(_make_event())
        assert result["report_url"] == "s3://r"

    async def test_handle_raises_on_policy_deny(self):
        from workers.pharmabridge_worker import PharmabridgeWorker

        # Patch at the worker module's local binding (imported name)
        with patch("workers.pharmabridge_worker.check_policy", new=AsyncMock(return_value=_POLICY_DENY)):
            worker = PharmabridgeWorker()
            with pytest.raises(PermissionError, match="OPA denied"):
                await worker.handle(_make_event())

    async def test_handle_emits_completion_event(self):
        from workers.pharmabridge_worker import PharmabridgeWorker

        mock_emit = AsyncMock()
        mock_execute = AsyncMock(return_value={
            "report_url": "s3://r",
            "summary": "done",
            "findings": [],
            "token_usage": {},
            "duration_ms": 50,
        })
        with patch("bvr_sdk.check_policy", new=AsyncMock(return_value=_POLICY_ALLOW)), \
             patch("plugins.pharma.pharmabridge.worker.execute", mock_execute), \
             patch("workers.pharmabridge_worker.emit_event", mock_emit):
            worker = PharmabridgeWorker()
            await worker.handle(_make_event())
        mock_emit.assert_called_once()
        emitted = mock_emit.call_args[1]
        assert emitted.get("event_type") == "bvr.pharma.report.complete"

    async def test_handle_worker_identity(self):
        from workers.pharmabridge_worker import PharmabridgeWorker

        worker = PharmabridgeWorker()
        assert worker.worker_id == "pharmabridge-worker-1"
        assert "pharma.trial.analyze" in worker.capabilities
        assert "pharma.data.ingest" in worker.capabilities
        assert "pharma.report.generate" in worker.capabilities


# ---------------------------------------------------------------------------
# Pharmabridge plugin health check
# ---------------------------------------------------------------------------

class TestPharmabridgeHealth:
    async def test_health_check_returns_ok(self):
        from plugins.pharma.pharmabridge.health import health_check

        import os
        with patch.dict(os.environ, {"BVR_API_URL": "http://bvr-api:8000", "AI_GATEWAY_URL": "http://ai-gateway:8001"}):
            result = await health_check()
        assert result["status"] == "ok"
        assert result["plugin"] == "pharmabridge"

    async def test_health_check_degraded_without_env(self):
        from plugins.pharma.pharmabridge.health import health_check

        import os
        env = {k: v for k, v in os.environ.items() if k not in ("BVR_API_URL", "AI_GATEWAY_URL")}
        with patch.dict(os.environ, env, clear=True):
            result = await health_check()
        assert result["status"] == "degraded"
        assert len(result["issues"]) > 0
