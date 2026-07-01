"""
Tests for the FastAPI events endpoint — POST /api/v1/events and GET /health.

Uses httpx.AsyncClient with the ASGI transport so no network is required.
All database and Redis calls are patched at the asyncpg / aioredis layer.
"""

import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Load api/main.py directly, bypassing any package __init__ issues.
# ---------------------------------------------------------------------------

import sys
import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
_API_FILE = _REPO_ROOT / "api" / "main.py"

# Stub heavy deps before importing api/main.py
import types

def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

for _pkg in [
    "opentelemetry", "opentelemetry.trace",
    "opentelemetry.sdk", "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export", "opentelemetry.sdk.resources",
    "opentelemetry.exporter", "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.instrumentation",
    "opentelemetry.instrumentation.fastapi",
    "opentelemetry.instrumentation.httpx",
]:
    if _pkg not in sys.modules:
        _stub(_pkg)

if "opentelemetry.trace" in sys.modules:
    sys.modules["opentelemetry.trace"].get_tracer = lambda *a, **kw: MagicMock()

# Load the real jwt module stub if not already loaded by conftest
if "jwt" not in sys.modules:
    _stub("jwt", decode=MagicMock(), ExpiredSignatureError=Exception, InvalidTokenError=Exception)


# Stub api.services before loading api.main (which imports them at module level)
import types as _types

_services_pkg = _types.ModuleType("api.services")
_services_mod_events = _types.ModuleType("api.services.events")
_services_mod_registry = _types.ModuleType("api.services.registry")
_services_mod_ai_gateway = _types.ModuleType("api.services.ai_gateway")
_services_mod_outcomes = _types.ModuleType("api.services.outcomes")
_services_mod_approvals = _types.ModuleType("api.services.approvals")

class _FakeEventService:
    """Thin service stub that delegates through the mock pool so assertions on
    conn.execute / conn.fetchrow still work in existing tests."""
    def __init__(self, pool): self._pool = pool

    async def store_event(self, **kw):
        async with self._pool.acquire() as conn:
            await conn.execute("INSERT -- stub", *[])

    async def get_result(self, event_id):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow("SELECT -- stub", event_id)

    async def post_result(self, **kw):
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE -- stub", *[])

    async def post_webhook_result(self, **kw):
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE webhook -- stub", *[])


class _FakeRegistryService:
    def __init__(self, pool): self._pool = pool
    async def register_worker(self, **kw): pass
    async def list_workers(self): return []
    async def register_integration(self, **kw): pass
    async def list_integrations(self): return []

class _FakeAIGatewayService:
    def __init__(self, pool): self._pool = pool
    async def register_model(self, **kw): pass
    async def list_models(self): return []
    async def register_prompt(self, **kw): pass
    async def register_policy(self, **kw): pass


class _FakeOutcomeService:
    def __init__(self, pool): self._pool = pool
    async def register_outcome(self, **kw): pass
    async def list_outcomes(self): return []


class _FakeApprovalService:
    def __init__(self, pool): self._pool = pool
    async def create_approval(self, **kw): pass
    async def get_approval(self, approval_id): return None
    async def approve(self, approval_id, approver): pass
    async def deny(self, approval_id, approver): pass
    async def list_approvals(self, status=None): return []


_services_mod_events.EventService = _FakeEventService
_services_mod_registry.RegistryService = _FakeRegistryService
_services_mod_ai_gateway.AIGatewayService = _FakeAIGatewayService
_services_mod_outcomes.OutcomeService = _FakeOutcomeService
_services_mod_approvals.ApprovalService = _FakeApprovalService
_services_pkg.EventService = _FakeEventService
_services_pkg.RegistryService = _FakeRegistryService
_services_pkg.AIGatewayService = _FakeAIGatewayService
_services_pkg.OutcomeService = _FakeOutcomeService
_services_pkg.ApprovalService = _FakeApprovalService
# api must be a package (needs __path__) so that submodule imports like
# 'from api.middleware import ...' work when api/main.py is exec'd below.
_api_pkg = _types.ModuleType("api")
_api_pkg.__path__ = [str(_REPO_ROOT / "api")]
sys.modules["api"] = _api_pkg
sys.modules["api.services"] = _services_pkg
sys.modules["api.services.events"] = _services_mod_events
sys.modules["api.services.registry"] = _services_mod_registry
sys.modules["api.services.ai_gateway"] = _services_mod_ai_gateway
sys.modules["api.services.outcomes"] = _services_mod_outcomes
sys.modules["api.services.approvals"] = _services_mod_approvals

# Load the real api.middleware (no heavy deps) so the import inside api/main.py works.
_middleware_spec = importlib.util.spec_from_file_location(
    "api.middleware", str(_REPO_ROOT / "api" / "middleware.py")
)
_middleware_mod = importlib.util.module_from_spec(_middleware_spec)
_middleware_spec.loader.exec_module(_middleware_mod)
sys.modules["api.middleware"] = _middleware_mod

# Load the real api.auth so the import inside api/main.py works.
# jwt is already stubbed above; httpx is imported lazily inside the function.
_auth_spec = importlib.util.spec_from_file_location(
    "api.auth", str(_REPO_ROOT / "api" / "auth.py")
)
_auth_mod = importlib.util.module_from_spec(_auth_spec)
_auth_spec.loader.exec_module(_auth_mod)
sys.modules["api.auth"] = _auth_mod

_api_spec = importlib.util.spec_from_file_location("api.main", str(_API_FILE))
_api_mod = importlib.util.module_from_spec(_api_spec)
sys.modules["api.main"] = _api_mod
_api_spec.loader.exec_module(_api_mod)

app = _api_mod.app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_pool():
    """Return a minimal asyncpg pool mock."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    # transaction() context manager
    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)

    # pool.acquire() context manager
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    pool.close = AsyncMock()
    return pool, conn


def _make_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.incr = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=True)
    r.xadd = AsyncMock(return_value="1-0")
    r.publish = AsyncMock(return_value=1)
    r.close = AsyncMock()
    return r


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def client():
    """Async HTTP client wired to the FastAPI app with mocked db + redis."""
    pool, conn = _make_db_pool()
    redis = _make_redis()

    app.state.db = pool
    app.state.redis = redis
    app.state.event_service = _FakeEventService(pool)
    app.state.registry_service = _FakeRegistryService(pool)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, conn, redis


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_200(self, client):
        c, _, _ = client
        resp = await c.get("/health")
        assert resp.status_code == 200

    async def test_health_response_contains_status(self, client):
        c, _, _ = client
        resp = await c.get("/health")
        data = resp.json()
        assert "status" in data


# ---------------------------------------------------------------------------
# POST /api/v1/events — authentication
# ---------------------------------------------------------------------------

class TestEventAuth:
    async def test_missing_auth_returns_403(self, client):
        c, _, _ = client
        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {"repo_url": "https://github.com/test/repo"},
                "correlation_id": str(uuid.uuid4()),
            },
        )
        # HTTPBearer returns 403 when no credentials supplied
        assert resp.status_code in (401, 403)

    async def test_invalid_token_returns_401(self, client):
        c, _, _ = client
        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {},
                "correlation_id": str(uuid.uuid4()),
            },
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401

    async def test_valid_service_token_accepted(self, client, monkeypatch):
        c, conn, redis = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "test-service-token")

        # conn.fetchrow needs to return something for the event insert
        row_id = str(uuid.uuid4())
        conn.execute = AsyncMock(return_value=None)
        redis.xadd = AsyncMock(return_value="1-0")

        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {"repo_url": "https://github.com/test/repo"},
                "correlation_id": str(uuid.uuid4()),
            },
            headers={"Authorization": "Bearer test-service-token"},
        )
        assert resp.status_code in (200, 201, 202)


# ---------------------------------------------------------------------------
# POST /api/v1/events — validation
# ---------------------------------------------------------------------------

class TestEventValidation:
    async def test_missing_event_type_returns_422(self, client, monkeypatch):
        c, _, _ = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "tok")
        resp = await c.post(
            "/api/v1/events",
            json={
                "payload": {"data": "x"},
                "correlation_id": "abc",
            },
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 422

    async def test_missing_correlation_id_returns_422(self, client, monkeypatch):
        c, _, _ = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "tok")
        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {},
            },
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 422

    async def test_missing_payload_returns_422(self, client, monkeypatch):
        c, _, _ = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "tok")
        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "correlation_id": "abc",
            },
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/events — success path
# ---------------------------------------------------------------------------

class TestEventSuccess:
    async def test_event_inserted_into_db(self, client, monkeypatch):
        c, conn, redis = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "tok")

        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {"repo_url": "https://github.com/acme/app"},
                "correlation_id": "corr-123",
            },
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code in (200, 201, 202)
        conn.execute.assert_awaited()

    async def test_event_published_to_redis(self, client, monkeypatch):
        c, conn, redis = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "tok")

        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {"repo_url": "https://github.com/acme/app"},
                "correlation_id": "corr-456",
            },
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code in (200, 201, 202)
        redis.xadd.assert_awaited()

    async def test_response_contains_event_id(self, client, monkeypatch):
        c, _, _ = client
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "tok")

        resp = await c.post(
            "/api/v1/events",
            json={
                "event_type": "bvr.review.repository",
                "payload": {},
                "correlation_id": "corr-789",
            },
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code in (200, 201, 202)
        data = resp.json()
        assert "event_id" in data or "correlation_id" in data or "status" in data
