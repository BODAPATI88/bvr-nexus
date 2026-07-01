"""
Unit tests for api.services — EventService and RegistryService.

Uses an AsyncMock pool (same helper as test_events_endpoint.py) so no live
database is required.
"""

import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import sys

# ---------------------------------------------------------------------------
# Load the real service modules directly (bypasses any sys.modules stubs
# injected by other test files for api.services.events / api.services.registry)
# ---------------------------------------------------------------------------

import importlib.util
import types as _types

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()

# Ensure asyncpg is importable (stub if not installed in test env)
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = _types.ModuleType("asyncpg")


def _load_svc(dotted: str, path: str):
    spec = importlib.util.spec_from_file_location(dotted, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_events_svc_mod = _load_svc(
    "api.services.events_real",
    str(_REPO_ROOT / "api" / "services" / "events.py"),
)
_registry_svc_mod = _load_svc(
    "api.services.registry_real",
    str(_REPO_ROOT / "api" / "services" / "registry.py"),
)

EventService = _events_svc_mod.EventService
RegistryService = _registry_svc_mod.RegistryService


# ---------------------------------------------------------------------------
# Pool factory
# ---------------------------------------------------------------------------

def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool, conn


# ---------------------------------------------------------------------------
# EventService
# ---------------------------------------------------------------------------

class TestEventServiceStoreEvent:
    async def test_store_event_calls_execute(self):
        pool, conn = _make_pool()
        svc = EventService(pool)
        event_id = str(uuid.uuid4())

        await svc.store_event(
            event_id=event_id,
            event_type="review.repository",
            payload={"repo_url": "https://github.com/test/repo"},
            correlation_id="corr-1",
            source="api",
            priority="normal",
            user_id=None,
        )

        conn.execute.assert_awaited_once()

    async def test_store_event_passes_event_id_as_first_arg(self):
        pool, conn = _make_pool()
        svc = EventService(pool)
        event_id = str(uuid.uuid4())

        await svc.store_event(
            event_id=event_id,
            event_type="review.repository",
            payload={},
            correlation_id="c",
            source="api",
            priority="normal",
            user_id=None,
        )

        args = conn.execute.call_args[0]
        # First positional after the SQL string is the event_id
        assert event_id in args


class TestEventServiceGetResult:
    async def test_get_result_returns_none_when_not_found(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = EventService(pool)

        result = await svc.get_result(str(uuid.uuid4()))

        assert result is None

    async def test_get_result_calls_fetchrow(self):
        pool, conn = _make_pool()
        svc = EventService(pool)
        await svc.get_result("some-event-id")
        conn.fetchrow.assert_awaited_once()


class TestEventServicePostResult:
    async def test_post_result_uses_transaction(self):
        pool, conn = _make_pool()
        svc = EventService(pool)

        await svc.post_result(
            event_id="evt-1",
            status="completed",
            result={"score": 90},
            artifact_urls=None,
            metrics=None,
        )

        conn.transaction.assert_called()

    async def test_post_result_calls_execute_twice(self):
        """Expects INSERT event_results + UPDATE events."""
        pool, conn = _make_pool()
        svc = EventService(pool)

        await svc.post_result(
            event_id="evt-2",
            status="completed",
            result={"score": 85},
            artifact_urls=["http://minio/x"],
            metrics={"duration_ms": 1000},
        )

        assert conn.execute.await_count == 2

    async def test_post_result_serialises_result_as_json(self):
        pool, conn = _make_pool()
        svc = EventService(pool)
        result_data = {"issues": [], "score": 77}

        await svc.post_result(
            event_id="evt-3",
            status="completed",
            result=result_data,
            artifact_urls=None,
            metrics=None,
        )

        first_call_args = conn.execute.call_args_list[0][0]
        # The second positional arg after SQL is the JSON-encoded result
        assert json.dumps(result_data) in first_call_args

    async def test_post_webhook_result_uses_correlation_id(self):
        pool, conn = _make_pool()
        svc = EventService(pool)
        corr = "corr-webhook-123"

        await svc.post_webhook_result(
            correlation_id=corr,
            status="completed",
            result={"summary": "ok"},
            artifact_urls=None,
            metrics=None,
        )

        all_args = [str(a) for call in conn.execute.call_args_list for a in call[0]]
        assert corr in all_args


# ---------------------------------------------------------------------------
# RegistryService
# ---------------------------------------------------------------------------

class TestRegistryServiceWorkers:
    async def test_register_worker_calls_execute(self):
        pool, conn = _make_pool()
        svc = RegistryService(pool)

        await svc.register_worker(
            worker_id="review-worker",
            capabilities=["review.repository"],
            health_endpoint="/health/review-worker",
            version="2.0.0",
        )

        conn.execute.assert_awaited_once()

    async def test_register_worker_passes_worker_id(self):
        pool, conn = _make_pool()
        svc = RegistryService(pool)

        await svc.register_worker(
            worker_id="my-worker",
            capabilities=[],
            health_endpoint="/h",
            version="1.0",
        )

        args = conn.execute.call_args[0]
        assert "my-worker" in args

    async def test_list_workers_calls_fetch(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = RegistryService(pool)

        result = await svc.list_workers()

        conn.fetch.assert_awaited_once()
        assert isinstance(result, list)


class TestRegistryServiceIntegrations:
    async def test_register_integration_calls_execute(self):
        pool, conn = _make_pool()
        svc = RegistryService(pool)

        await svc.register_integration(
            id="plugins.ai.claude",
            name="Claude",
            type_="ai",
            version="1.0.0",
            capabilities=["code_analysis"],
            status="active",
        )

        conn.execute.assert_awaited_once()

    async def test_list_integrations_returns_list(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = RegistryService(pool)

        result = await svc.list_integrations()

        assert isinstance(result, list)
