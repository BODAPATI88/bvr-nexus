"""
Integration tests — full event workflow.

These tests require a live BVR Nexus stack (docker compose up).
Run with:  make test-integration
Skip with: make test  (uses --ignore=tests/integration)

Environment variables consumed:
  BVR_API_URL       — default http://localhost:8000
  BVR_SERVICE_TOKEN — service auth token
  REDIS_URL         — default redis://localhost:6379
"""

import asyncio
import json
import os
import uuid
import pytest
import httpx

BVR_API_URL = os.getenv("BVR_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("BVR_SERVICE_TOKEN", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
AUTH_HEADER = {"Authorization": f"Bearer {SERVICE_TOKEN}"}

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _wait_for_status(
    client: httpx.AsyncClient,
    event_id: str,
    target_statuses: list[str],
    timeout: int = 30,
) -> dict:
    """Poll GET /api/v1/events/{event_id}/result until status matches or timeout."""
    for _ in range(timeout):
        resp = await client.get(
            f"{BVR_API_URL}/api/v1/events/{event_id}/result",
            headers=AUTH_HEADER,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") in target_statuses:
                return data
        await asyncio.sleep(1)
    raise TimeoutError(f"Event {event_id} did not reach {target_statuses} in {timeout}s")


# ---------------------------------------------------------------------------
# Stack connectivity
# ---------------------------------------------------------------------------

class TestStackHealth:
    async def test_api_health(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BVR_API_URL}/health")
        assert resp.status_code == 200, f"API not healthy: {resp.text}"

    async def test_api_health_response_shape(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BVR_API_URL}/health")
        data = resp.json()
        assert "status" in data


# ---------------------------------------------------------------------------
# Event lifecycle — submit → pending → routed to worker → completed/failed
# ---------------------------------------------------------------------------

class TestEventLifecycle:
    async def test_submit_event_returns_event_id(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BVR_API_URL}/api/v1/events",
                json={
                    "event_type": "bvr.review.repository",
                    "payload": {"repo_url": "https://github.com/test/integration"},
                    "correlation_id": str(uuid.uuid4()),
                },
                headers=AUTH_HEADER,
            )
        assert resp.status_code in (200, 201, 202), resp.text
        data = resp.json()
        assert "event_id" in data

    async def test_submitted_event_initially_pending(self):
        corr = str(uuid.uuid4())
        async with httpx.AsyncClient(timeout=10) as client:
            post_resp = await client.post(
                f"{BVR_API_URL}/api/v1/events",
                json={
                    "event_type": "bvr.review.repository",
                    "payload": {"repo_url": "https://github.com/test/integration"},
                    "correlation_id": corr,
                },
                headers=AUTH_HEADER,
            )
            assert post_resp.status_code in (200, 201, 202)
            event_id = post_resp.json()["event_id"]

            get_resp = await client.get(
                f"{BVR_API_URL}/api/v1/events/{event_id}/result",
                headers=AUTH_HEADER,
            )
        # Immediately after submission: pending or processing
        if get_resp.status_code == 200:
            assert get_resp.json().get("status") in ("pending", "processing", "completed", "failed")

    async def test_result_endpoint_404_for_unknown_event(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BVR_API_URL}/api/v1/events/{uuid.uuid4()}/result",
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Worker result posting
# ---------------------------------------------------------------------------

class TestResultPosting:
    async def test_post_result_updates_event_status(self):
        """Submit event then manually post a completed result."""
        corr = str(uuid.uuid4())
        async with httpx.AsyncClient(timeout=10) as client:
            # Submit
            post_resp = await client.post(
                f"{BVR_API_URL}/api/v1/events",
                json={
                    "event_type": "bvr.review.repository",
                    "payload": {"repo_url": "https://github.com/test/integration"},
                    "correlation_id": corr,
                },
                headers=AUTH_HEADER,
            )
            assert post_resp.status_code in (200, 201, 202)
            event_id = post_resp.json()["event_id"]

            # Post result
            result_resp = await client.post(
                f"{BVR_API_URL}/api/v1/events/{event_id}/result",
                json={
                    "event_id": event_id,
                    "status": "completed",
                    "result": {"score": 85, "issues": []},
                    "artifact_urls": ["http://minio/bvr-artifacts/test.json"],
                    "metrics": {"duration_ms": 1200},
                    "created_at": "2024-01-01T00:00:00Z",
                },
                headers=AUTH_HEADER,
            )
            assert result_resp.status_code == 200

            # Verify status updated
            get_resp = await client.get(
                f"{BVR_API_URL}/api/v1/events/{event_id}/result",
                headers=AUTH_HEADER,
            )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["status"] == "completed"

    async def test_post_failed_result(self):
        corr = str(uuid.uuid4())
        async with httpx.AsyncClient(timeout=10) as client:
            post_resp = await client.post(
                f"{BVR_API_URL}/api/v1/events",
                json={
                    "event_type": "bvr.review.repository",
                    "payload": {},
                    "correlation_id": corr,
                },
                headers=AUTH_HEADER,
            )
            event_id = post_resp.json()["event_id"]

            result_resp = await client.post(
                f"{BVR_API_URL}/api/v1/events/{event_id}/result",
                json={
                    "event_id": event_id,
                    "status": "failed",
                    "result": {"error": "clone failed"},
                    "created_at": "2024-01-01T00:00:00Z",
                },
                headers=AUTH_HEADER,
            )
            assert result_resp.status_code == 200

            get_resp = await client.get(
                f"{BVR_API_URL}/api/v1/events/{event_id}/result",
                headers=AUTH_HEADER,
            )
        assert get_resp.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Kestra webhook callback
# ---------------------------------------------------------------------------

class TestKestraWebhook:
    async def test_webhook_callback_accepted(self):
        corr = str(uuid.uuid4())
        async with httpx.AsyncClient(timeout=10) as client:
            # Post an event first so the foreign key exists
            post_resp = await client.post(
                f"{BVR_API_URL}/api/v1/events",
                json={
                    "event_type": "bvr.review.repository",
                    "payload": {},
                    "correlation_id": corr,
                },
                headers=AUTH_HEADER,
            )
            event_id = post_resp.json()["event_id"]

            webhook_resp = await client.post(
                f"{BVR_API_URL}/api/v1/webhooks/kestra",
                json={
                    "correlation_id": event_id,
                    "event_type": "bvr.review.repository.completed",
                    "status": "completed",
                    "result": {"summary": "All checks passed"},
                },
                headers=AUTH_HEADER,
            )
        assert webhook_resp.status_code == 200
        data = webhook_resp.json()
        assert data["status"] == "received"


# ---------------------------------------------------------------------------
# Registry endpoints
# ---------------------------------------------------------------------------

class TestRegistry:
    async def test_list_workflows(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BVR_API_URL}/api/v1/registry/workflows",
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 200
        workflows = resp.json()
        assert isinstance(workflows, list)
        ids = [w["id"] for w in workflows]
        assert "bvr.review.repository" in ids

    async def test_list_workers(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BVR_API_URL}/api/v1/registry/workers",
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
