"""
Pharmabridge plugin execution logic.
Invoked by PharmabridgeWorker via BaseWorker._handle_event().
All LLM calls go through bvr_sdk.ai_gateway_call; all storage via bvr_sdk.upload_artifact.
"""
from __future__ import annotations

import json
import time
from typing import Any

from bvr_sdk import ai_gateway_call, upload_artifact, emit_event


_ANALYSIS_PROMPTS = {
    "efficacy": (
        "You are a clinical trial data analyst. Analyse the following trial data for efficacy signals. "
        "Report: primary endpoint results, statistical significance (p-value), effect size, "
        "and any noteworthy subgroup findings. Be precise and cite values from the data."
    ),
    "safety": (
        "You are a clinical trial safety reviewer. Analyse the following trial data for adverse events. "
        "Classify findings by severity (mild/moderate/severe/serious), calculate incidence rates, "
        "identify any dose-response relationships, and flag anything requiring immediate attention."
    ),
    "enrollment": (
        "You are a clinical trial enrollment analyst. Analyse the following trial data for enrollment metrics. "
        "Report: current vs target enrollment, dropout rate, site performance, "
        "demographic distribution, and projected completion timeline."
    ),
}


async def execute(event_payload: dict[str, Any], sdk_context: dict[str, Any]) -> dict[str, Any]:
    """
    Main Pharmabridge execution function.
    Called by PharmabridgeWorker.handle() with the validated event payload.
    """
    start_ms = int(time.monotonic() * 1000)

    trial_id = event_payload["trial_id"]
    data_source = event_payload["data_source"]
    analysis_type = event_payload["analysis_type"]
    data_url = event_payload.get("data_url", "")

    system_prompt = event_payload.get("prompt_override") or _ANALYSIS_PROMPTS[analysis_type]

    user_prompt = (
        f"Trial ID: {trial_id}\n"
        f"Data format: {data_source.upper()}\n"
        f"Analysis type: {analysis_type}\n"
        f"Data source: {data_url or '(no data URL provided — use registered trial data)'}\n\n"
        f"Perform the requested {analysis_type} analysis. Return structured JSON with keys: "
        f"summary (string), findings (array of {{category, severity, description}}), "
        f"and recommendations (array of strings)."
    )

    ai_result = await ai_gateway_call(
        capability="pharma.trial.analyze",
        prompt=user_prompt,
        system_prompt=system_prompt,
        model_preference="claude",
    )

    raw_text: str = ai_result.get("content", "") if isinstance(ai_result, dict) else str(ai_result)

    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        parsed = {
            "summary": raw_text[:500] if raw_text else "Analysis complete.",
            "findings": [],
            "recommendations": [],
        }

    report = {
        "trial_id": trial_id,
        "analysis_type": analysis_type,
        "data_source": data_source,
        "summary": parsed.get("summary", ""),
        "findings": parsed.get("findings", []),
        "recommendations": parsed.get("recommendations", []),
        "generated_at": sdk_context.get("timestamp", ""),
    }

    report_key = f"pharmabridge/reports/{trial_id}/{analysis_type}.json"
    report_url = await upload_artifact(
        key=report_key,
        data=json.dumps(report, indent=2).encode(),
        content_type="application/json",
    )

    if event_payload.get("notify_slack"):
        await emit_event(
            event_type="bvr.notification.send",
            payload={
                "channel": "#pharmabridge",
                "message": (
                    f"Pharmabridge analysis complete — *{trial_id}* ({analysis_type})\n"
                    f"Report: {report_url}"
                ),
            },
        )

    duration_ms = int(time.monotonic() * 1000) - start_ms
    token_usage = ai_result.get("usage", {}) if isinstance(ai_result, dict) else {}

    return {
        "report_url": report_url or report_key,
        "summary": report["summary"],
        "findings": report["findings"],
        "token_usage": {
            "input_tokens": token_usage.get("input_tokens", 0),
            "output_tokens": token_usage.get("output_tokens", 0),
            "cost_usd": token_usage.get("cost_usd", 0.0),
        },
        "duration_ms": duration_ms,
    }
