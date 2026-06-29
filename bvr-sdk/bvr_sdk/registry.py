"""
Platform registry client — Discover workers, integrations, models.
"""

import os
import httpx
from typing import Dict, Any, List, Optional

BVR_API_URL = os.getenv("BVR_API_URL", "http://localhost:8000")

async def register_worker(
    worker_id: str,
    capabilities: List[str],
    health_endpoint: str,
    version: str
) -> Dict[str, Any]:
    """Register a worker with the platform registry."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BVR_API_URL}/api/v1/registry/workers",
            json={
                "worker_id": worker_id,
                "capabilities": capabilities,
                "health_endpoint": health_endpoint,
                "version": version
            },
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()

async def discover_integration(integration_type: str) -> Optional[Dict[str, Any]]:
    """Discover an integration by type."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BVR_API_URL}/api/v1/registry/integrations",
            timeout=10.0
        )
        resp.raise_for_status()
        integrations = resp.json()
        for i in integrations:
            if i["type"] == integration_type and i["status"] == "active":
                return i
        return None

async def discover_model(capability: str) -> Optional[Dict[str, Any]]:
    """Discover the best model for a given capability."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BVR_API_URL}/api/v1/ai-gateway/models",
            timeout=10.0
        )
        resp.raise_for_status()
        models = resp.json()
        # Sort by priority, filter by capability
        capable = [m for m in models if capability in m.get("capabilities", [])]
        capable.sort(key=lambda m: m.get("priority", 999))
        return capable[0] if capable else None
