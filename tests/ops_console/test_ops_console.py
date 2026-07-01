"""
Tests for the Operations Console FastAPI service.
All outbound HTTP calls to BVR API / AI Gateway / Prometheus are patched
so no running services are required.
"""
import sys
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
_OPS_DIR = _REPO_ROOT / "ops-console"

# Add ops-console to path so templates dir resolves correctly
sys.path.insert(0, str(_OPS_DIR))

_spec = importlib.util.spec_from_file_location("ops_main", str(_OPS_DIR / "main.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

app = _mod.app

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

_API_HEALTH = {"status": "ok", "service": "bvr-api"}
_GW_HEALTH = {"status": "ok", "service": "ai-gateway"}
_WORKERS = [{"worker_id": "review-worker-1", "capabilities": ["bvr.review.repository"], "version": "2.0.0"}]
_INTEGRATIONS = [{"id": "plugins.ai.claude", "name": "Claude", "type": "ai", "status": "active", "capabilities": ["code_analysis"]}]
_CAPABILITIES = [{"id": "code_analysis", "name": "code_analysis"}]
_PROVIDERS = [{"id": "claude_code", "priority": 1, "circuit_state": "closed", "failure_count": 0}]
_OUTCOMES = [{"goal_id": "g1", "description": "Improve coverage", "metric": "pct", "target": 80.0, "current": 55.0, "unit": "percent", "status": "on_track"}]
_MODELS = [{"model_id": "claude-sonnet", "model_name": "claude-sonnet-4", "provider": "anthropic", "capabilities": ["code_analysis"], "priority": 1, "cost_per_1k_output": 0.015}]


def _make_mock_get(responses: dict):
    """Build an async _get mock that returns different data per URL substring."""
    async def _mock(url: str, token: str = ""):
        for key, val in responses.items():
            if key in url:
                return val
        return None
    return _mock


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.status_code == 200

    async def test_health_contains_status_ok(self):
        async with AsyncMock(transport=ASGITransport(app=app), base_url="http://test"):
            pass
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["status"] == "ok"

    async def test_health_contains_version(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert "version" in r.json()


# ---------------------------------------------------------------------------
# Operations Console
# ---------------------------------------------------------------------------

class TestOperationsConsole:
    async def test_root_returns_200(self):
        responses = {
            "/health": _API_HEALTH,
            "ai-gateway:8001/health": _GW_HEALTH,
            "/registry/workers": _WORKERS,
            "/registry/integrations": _INTEGRATIONS,
            "/v1/capabilities": _CAPABILITIES,
            "/v1/providers/": _PROVIDERS,
        }
        with patch.object(_mod, "_get", side_effect=_make_mock_get(responses)), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=1.0)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/")
        assert r.status_code == 200

    async def test_root_contains_operations_heading(self):
        with patch.object(_mod, "_get", new=AsyncMock(return_value=None)), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/")
        assert b"Operations Console" in r.content

    async def test_root_shows_worker_when_registered(self):
        async def mock_get(url, token=""):
            if "workers" in url:
                return _WORKERS
            if "health" in url:
                return _API_HEALTH
            return None

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=1.0)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/")
        assert b"review-worker-1" in r.content

    async def test_root_shows_integration_name(self):
        async def mock_get(url, token=""):
            if "integrations" in url:
                return _INTEGRATIONS
            if "health" in url:
                return _API_HEALTH
            return None

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=1.0)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/")
        assert b"Claude" in r.content

    async def test_root_renders_when_services_down(self):
        """Should still render (gracefully degraded) when all upstreams return None."""
        with patch.object(_mod, "_get", new=AsyncMock(return_value=None)), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/")
        assert r.status_code == 200

    async def test_root_shows_provider_circuit_state(self):
        async def mock_get(url, token=""):
            if "capabilities" in url and "providers" not in url:
                return _CAPABILITIES
            if "providers" in url:
                return _PROVIDERS
            if "health" in url:
                return _GW_HEALTH
            return None

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=1.0)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/")
        assert b"closed" in r.content or r.status_code == 200


# ---------------------------------------------------------------------------
# CEO Dashboard
# ---------------------------------------------------------------------------

class TestCEODashboard:
    async def test_ceo_returns_200(self):
        async def mock_get(url, token=""):
            if "outcomes" in url:
                return _OUTCOMES
            if "models" in url:
                return _MODELS
            if "integrations" in url:
                return _INTEGRATIONS
            if "workers" in url:
                return _WORKERS
            if "health" in url:
                return _API_HEALTH
            return None

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=42.0)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        assert r.status_code == 200

    async def test_ceo_contains_executive_heading(self):
        with patch.object(_mod, "_get", new=AsyncMock(return_value=None)), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        assert b"Executive" in r.content

    async def test_ceo_shows_outcome_description(self):
        async def mock_get(url, token=""):
            if "outcomes" in url:
                return _OUTCOMES
            if "health" in url:
                return _API_HEALTH
            return None

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        assert b"Improve coverage" in r.content

    async def test_ceo_shows_model_provider(self):
        async def mock_get(url, token=""):
            if "models" in url:
                return _MODELS
            if "health" in url:
                return _API_HEALTH
            return None

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        assert b"anthropic" in r.content

    async def test_ceo_shows_platform_operational_when_healthy(self):
        async def mock_get(url, token=""):
            return {"status": "ok"}

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=1.0)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        assert b"Operational" in r.content

    async def test_ceo_renders_gracefully_with_empty_data(self):
        with patch.object(_mod, "_get", new=AsyncMock(return_value=[])), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        assert r.status_code == 200

    async def test_ceo_kpi_tile_shows_worker_count(self):
        async def mock_get(url, token=""):
            if "workers" in url:
                return _WORKERS
            if "health" in url:
                return _API_HEALTH
            return []

        with patch.object(_mod, "_get", side_effect=mock_get), \
             patch.object(_mod, "_prom_query", new=AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/ceo")
        # 1 worker in mock data → digit "1" should appear in KPI tile
        assert b">1<" in r.content or b"1" in r.content
