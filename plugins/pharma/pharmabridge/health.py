"""
Pharmabridge plugin health check.
Called by BaseWorker at startup and periodically by the platform registry.
"""
from __future__ import annotations

import os
from typing import Any


async def health_check() -> dict[str, Any]:
    """Return plugin health. Checks that required environment context is available."""
    issues: list[str] = []

    bvr_api = os.getenv("BVR_API_URL")
    if not bvr_api:
        issues.append("BVR_API_URL not set")

    ai_gw = os.getenv("AI_GATEWAY_URL")
    if not ai_gw:
        issues.append("AI_GATEWAY_URL not set")

    status = "ok" if not issues else "degraded"
    return {
        "status": status,
        "plugin": "pharmabridge",
        "version": "1.0.0",
        "issues": issues,
    }
