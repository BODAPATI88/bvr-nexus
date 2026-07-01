"""
BVR Pharmabridge Worker — clinical trial data ingestion and analysis.
All LLM calls go through bvr_sdk.ai_gateway_call via the AI Gateway.
All storage uses bvr_sdk.upload_artifact (MinIO).
Direct provider SDK imports are forbidden.
"""
from __future__ import annotations

from typing import Any

from workers.base import BaseWorker
from bvr_sdk import EventEnvelope, emit_event, trace_span, check_policy


class PharmabridgeWorker(BaseWorker):
    worker_id = "pharmabridge-worker-1"
    capabilities = [
        "pharma.data.ingest",
        "pharma.trial.analyze",
        "pharma.report.generate",
    ]
    version = "1.0.0"

    @trace_span("pharmabridge.handle")
    async def handle(self, event: EventEnvelope) -> dict[str, Any]:
        payload = event.payload

        policy_allowed = await check_policy(
            "bvr/allow",
            {
                "event_type": event.event_type,
                "user_id": event.user_id,
                "payload": payload,
            },
        )
        if not policy_allowed:
            raise PermissionError(f"OPA denied pharmabridge event: {event.event_type}")

        sdk_context = {
            "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
            "correlation_id": event.correlation_id,
            "user_id": event.user_id,
        }

        from plugins.pharma.pharmabridge.worker import execute as pharma_execute
        result = await pharma_execute(payload, sdk_context)

        await emit_event(
            event_type="bvr.pharma.report.complete",
            payload={
                "trial_id": payload["trial_id"],
                "analysis_type": payload["analysis_type"],
                "report_url": result.get("report_url", ""),
                "summary": result.get("summary", ""),
                "duration_ms": result.get("duration_ms", 0),
            },
            correlation_id=event.correlation_id,
        )

        return result
