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


# ---------------------------------------------------------------------------
# Load new service modules
# ---------------------------------------------------------------------------

_ai_gateway_svc_mod = _load_svc(
    "api.services.ai_gateway_real",
    str(_REPO_ROOT / "api" / "services" / "ai_gateway.py"),
)
_outcomes_svc_mod = _load_svc(
    "api.services.outcomes_real",
    str(_REPO_ROOT / "api" / "services" / "outcomes.py"),
)
_approvals_svc_mod = _load_svc(
    "api.services.approvals_real",
    str(_REPO_ROOT / "api" / "services" / "approvals.py"),
)

AIGatewayService = _ai_gateway_svc_mod.AIGatewayService
OutcomeService = _outcomes_svc_mod.OutcomeService
ApprovalService = _approvals_svc_mod.ApprovalService


# ---------------------------------------------------------------------------
# AIGatewayService
# ---------------------------------------------------------------------------

class TestAIGatewayServiceModels:
    async def test_register_model_calls_execute(self):
        pool, conn = _make_pool()
        svc = AIGatewayService(pool)

        await svc.register_model(
            model_id="claude-sonnet-4",
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            capabilities=["code_analysis"],
            priority=1,
            fallback="gpt-4o",
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
        )

        conn.execute.assert_awaited_once()

    async def test_register_model_passes_model_id(self):
        pool, conn = _make_pool()
        svc = AIGatewayService(pool)

        await svc.register_model(
            model_id="my-model",
            provider="openai",
            model_name="gpt-4o",
            capabilities=["chat"],
            priority=2,
            fallback=None,
            cost_per_1k_input=0.0025,
            cost_per_1k_output=0.012,
        )

        args = conn.execute.call_args[0]
        assert "my-model" in args

    async def test_list_models_calls_fetch(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = AIGatewayService(pool)

        result = await svc.list_models()

        conn.fetch.assert_awaited_once()
        assert isinstance(result, list)


class TestAIGatewayServicePrompts:
    async def test_register_prompt_calls_execute(self):
        pool, conn = _make_pool()
        svc = AIGatewayService(pool)

        await svc.register_prompt(
            prompt_id="review-prompt-v1",
            version="1.0",
            template="Review the following code: {code}",
            variables=["code"],
            model_preference="claude",
        )

        conn.execute.assert_awaited_once()

    async def test_register_prompt_passes_prompt_id(self):
        pool, conn = _make_pool()
        svc = AIGatewayService(pool)

        await svc.register_prompt(
            prompt_id="my-prompt",
            version="2.0",
            template="Hello {name}",
            variables=["name"],
            model_preference=None,
        )

        args = conn.execute.call_args[0]
        assert "my-prompt" in args


class TestAIGatewayServicePolicies:
    async def test_register_policy_calls_execute(self):
        pool, conn = _make_pool()
        svc = AIGatewayService(pool)

        await svc.register_policy(
            policy_id="cost-guardrail",
            rego_path="governance/rego/cost.rego",
            description="Enforces per-execution cost limits",
            applies_to=["bvr.review", "bvr.achieve"],
        )

        conn.execute.assert_awaited_once()

    async def test_register_policy_passes_policy_id(self):
        pool, conn = _make_pool()
        svc = AIGatewayService(pool)

        await svc.register_policy(
            policy_id="rbac-policy",
            rego_path="governance/rego/bvr.rego",
            description="RBAC enforcement",
            applies_to=["*"],
        )

        args = conn.execute.call_args[0]
        assert "rbac-policy" in args


# ---------------------------------------------------------------------------
# OutcomeService
# ---------------------------------------------------------------------------

class TestOutcomeService:
    async def test_register_outcome_calls_execute(self):
        pool, conn = _make_pool()
        svc = OutcomeService(pool)

        await svc.register_outcome(
            goal_id="goal-improve-test-coverage",
            description="Increase test coverage to 80%",
            metric="coverage_pct",
            target=80.0,
            unit="percent",
            current=55.0,
            workflow_id="bvr.achieve.coverage",
            status="on_track",
        )

        conn.execute.assert_awaited_once()

    async def test_register_outcome_passes_goal_id(self):
        pool, conn = _make_pool()
        svc = OutcomeService(pool)

        await svc.register_outcome(
            goal_id="my-goal",
            description="Some goal",
            metric="count",
            target=100.0,
            unit="items",
            current=None,
            workflow_id="wf-1",
            status="on_track",
        )

        args = conn.execute.call_args[0]
        assert "my-goal" in args

    async def test_list_outcomes_returns_list(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = OutcomeService(pool)

        result = await svc.list_outcomes()

        conn.fetch.assert_awaited_once()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ApprovalService
# ---------------------------------------------------------------------------

class TestApprovalService:
    async def test_create_approval_calls_execute(self):
        pool, conn = _make_pool()
        svc = ApprovalService(pool)

        await svc.create_approval(
            approval_id="appr-001",
            action="deploy",
            resource="bvr-api",
            approvers=["alice@example.com"],
            status="pending",
            created_at="2026-07-01T00:00:00Z",
            expires_at="2026-07-02T00:00:00Z",
        )

        conn.execute.assert_awaited_once()

    async def test_create_approval_passes_approval_id(self):
        pool, conn = _make_pool()
        svc = ApprovalService(pool)

        await svc.create_approval(
            approval_id="my-appr",
            action="scale",
            resource="workers",
            approvers=["bob@example.com"],
            status="pending",
            created_at="2026-07-01T00:00:00Z",
            expires_at="2026-07-02T00:00:00Z",
        )

        args = conn.execute.call_args[0]
        assert "my-appr" in args

    async def test_get_approval_returns_none_when_not_found(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = ApprovalService(pool)

        result = await svc.get_approval("nonexistent")

        assert result is None

    async def test_get_approval_returns_dict_when_found(self):
        pool, conn = _make_pool()
        fake_row = {"approval_id": "appr-1", "status": "pending", "approvers": ["a@b.com"]}
        conn.fetchrow = AsyncMock(return_value=fake_row)
        svc = ApprovalService(pool)

        result = await svc.get_approval("appr-1")

        assert isinstance(result, dict)
        assert result["approval_id"] == "appr-1"

    async def test_approve_calls_execute(self):
        pool, conn = _make_pool()
        svc = ApprovalService(pool)

        await svc.approve("appr-1", "alice@example.com")

        conn.execute.assert_awaited_once()
        args = conn.execute.call_args[0]
        assert "alice@example.com" in args

    async def test_deny_calls_execute(self):
        pool, conn = _make_pool()
        svc = ApprovalService(pool)

        await svc.deny("appr-1", "bob@example.com")

        conn.execute.assert_awaited_once()
        args = conn.execute.call_args[0]
        assert "bob@example.com" in args

    async def test_list_approvals_no_filter(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = ApprovalService(pool)

        result = await svc.list_approvals()

        conn.fetch.assert_awaited_once()
        assert isinstance(result, list)

    async def test_list_approvals_with_status_filter(self):
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        svc = ApprovalService(pool)

        result = await svc.list_approvals(status="pending")

        conn.fetch.assert_awaited_once()
        # Verify the status filter was passed as an argument
        args = conn.fetch.call_args[0]
        assert "pending" in args
