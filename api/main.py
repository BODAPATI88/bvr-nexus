"""
BVR API Gateway — FastAPI Application Layer
Orchestrates between Kestra (orchestration) and BVR Workers (execution).
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import jwt
import redis.asyncio as aioredis
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from api.services import EventService, RegistryService

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Validate JWT token and return user info."""
    token = credentials.credentials

    try:
        import httpx as _httpx

        async with _httpx.AsyncClient() as client:
            resp = await client.get("http://keycloak:8080/realms/bvr", timeout=10.0)
            if resp.status_code == 200:
                realm_info = resp.json()
                public_key = realm_info.get("public_key", "")
                if public_key:
                    decoded = jwt.decode(
                        token,
                        key=f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----",
                        algorithms=["RS256"],
                        audience="bvr-api",
                        options={"verify_exp": True},
                    )
                    return decoded
    except Exception:
        pass

    # Fallback: check service token — no default; must be explicitly configured
    service_token = os.getenv("BVR_SERVICE_TOKEN")
    if service_token and token == service_token:
        return {"sub": "bvr-service", "roles": ["bvr-service"]}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
    )


async def require_role(role: str):
    """Dependency factory for role-based access control."""

    async def _check_role(user: dict = Depends(get_current_user)):
        roles = user.get("roles", [])
        if role not in roles and "bvr-admin" not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {role}",
            )
        return user

    return _check_role


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

INIT_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    correlation_id TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    priority TEXT DEFAULT 'normal',
    user_id TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS event_results (
    event_id UUID PRIMARY KEY REFERENCES events(event_id),
    result JSONB,
    artifact_urls JSONB,
    metrics JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    capabilities TEXT[] NOT NULL,
    health_endpoint TEXT NOT NULL,
    version TEXT NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS integrations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    version TEXT NOT NULL,
    capabilities TEXT[] NOT NULL,
    status TEXT DEFAULT 'active',
    manifest JSONB
);

CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    capabilities TEXT[] NOT NULL,
    priority INT NOT NULL,
    fallback TEXT,
    cost_per_1k_input FLOAT NOT NULL,
    cost_per_1k_output FLOAT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    template TEXT NOT NULL,
    variables TEXT[] NOT NULL,
    model_preference TEXT
);

CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    rego_path TEXT NOT NULL,
    description TEXT NOT NULL,
    applies_to TEXT[] NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    goal_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    metric TEXT NOT NULL,
    target FLOAT NOT NULL,
    unit TEXT NOT NULL,
    current FLOAT,
    workflow_id TEXT NOT NULL,
    status TEXT DEFAULT 'on_track'
);

CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
"""

# ---------------------------------------------------------------------------
# Lifespan — pool tuning + service wiring
# ---------------------------------------------------------------------------

_MAX_PAYLOAD_BYTES = int(os.getenv("BVR_MAX_PAYLOAD_BYTES", str(1 * 1024 * 1024)))  # 1 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = await aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True
    )
    app.state.db = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL").replace("+asyncpg", ""),
        min_size=2,
        max_size=10,
        max_inactive_connection_lifetime=300.0,
    )
    async with app.state.db.acquire() as conn:
        await conn.execute(INIT_SQL)

    app.state.event_service = EventService(app.state.db)
    app.state.registry_service = RegistryService(app.state.db)

    yield

    await app.state.redis.aclose()
    await app.state.db.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="BVR Nexus API",
    description="Application layer for BVR workflow orchestration",
    version="2.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class PayloadSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared Content-Length exceeds BVR_MAX_PAYLOAD_BYTES (1 MB)."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_PAYLOAD_BYTES:
            return Response(
                content='{"detail":"Request body too large"}',
                status_code=413,
                media_type="application/json",
            )
        return await call_next(request)


class ContentTypeMiddleware(BaseHTTPMiddleware):
    """Require application/json Content-Type on mutating requests."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            ct = request.headers.get("content-type", "")
            if not ct.startswith("application/json"):
                return Response(
                    content='{"detail":"Content-Type must be application/json"}',
                    status_code=415,
                    media_type="application/json",
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple Redis-based rate limiting (100 req/min per client)."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        client_id = request.headers.get("X-API-Key", request.client.host)
        redis = request.app.state.redis
        key = f"rate_limit:{client_id}"
        current = await redis.get(key)

        if current and int(current) >= 100:
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
            )

        await redis.incr(key)
        await redis.expire(key, 60)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with correlation IDs and timing."""

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        start_time = time.time()
        print(
            f"[REQUEST] {correlation_id} {request.method} {request.url.path} {request.client.host}"
        )
        response = await call_next(request)
        duration = time.time() - start_time
        print(f"[RESPONSE] {correlation_id} {response.status_code} {duration:.3f}s")
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        return response


# Middleware registration order: outermost (first added) wraps all inner ones.
# PayloadSize and ContentType must run before route handlers touch the body.
app.add_middleware(PayloadSizeMiddleware)
app.add_middleware(ContentTypeMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)

_allowed_origins = [
    o.strip()
    for o in os.getenv("API_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    payload: Dict[str, Any]
    correlation_id: str
    source: str = "api"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    priority: str = "normal"
    user_id: Optional[str] = None


class EventResult(BaseModel):
    event_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    artifact_urls: Optional[List[str]] = None
    metrics: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class WorkflowDefinition(BaseModel):
    id: str
    namespace: str
    description: str
    tags: List[str]
    kestra_workflow_id: str


class WorkerRegistration(BaseModel):
    worker_id: str
    capabilities: List[str]
    health_endpoint: str
    version: str


class IntegrationManifest(BaseModel):
    id: str
    name: str
    type: str
    version: str
    capabilities: List[str]
    status: str = "active"


class ModelConfig(BaseModel):
    id: str
    provider: str
    model_name: str
    capabilities: List[str]
    priority: int
    fallback: Optional[str] = None
    cost_per_1k_input: float
    cost_per_1k_output: float


class PromptTemplate(BaseModel):
    id: str
    version: str
    template: str
    variables: List[str]
    model_preference: Optional[str] = None


class PolicyRule(BaseModel):
    id: str
    rego_path: str
    description: str
    applies_to: List[str]


class OutcomeMetric(BaseModel):
    goal_id: str
    description: str
    metric: str
    target: float
    unit: str
    current: Optional[float] = None
    workflow_id: str
    status: str = "on_track"


# ---------------------------------------------------------------------------
# Payload validation schemas
# ---------------------------------------------------------------------------

from pydantic import validator  # noqa: E402


class ReviewEventPayload(BaseModel):
    repo_url: str = Field(..., pattern=r"^https?://.*")
    branch: str = Field(default="main", min_length=1, max_length=100)


class ResearchEventPayload(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    depth: str = Field(default="standard", pattern=r"^(quick|standard|deep)$")


class AchieveEventPayload(BaseModel):
    resume_content: str = Field(..., min_length=50, max_length=50000)
    target_role: str = Field(default="Software Engineer", min_length=2, max_length=100)


EVENT_PAYLOAD_SCHEMAS = {
    "review.repository": ReviewEventPayload,
    "research.topic": ResearchEventPayload,
    "achieve.resume-optimization": AchieveEventPayload,
}


def validate_event_payload(event_type: str, payload: dict) -> dict:
    schema_class = EVENT_PAYLOAD_SCHEMAS.get(event_type)
    if schema_class:
        validated = schema_class(**payload)
        return validated.model_dump()
    return payload


# ---------------------------------------------------------------------------
# Event endpoints
# ---------------------------------------------------------------------------


@app.post("/api/v1/events", response_model=EventEnvelope)
async def emit_event(
    event: EventEnvelope,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Receive, validate, store, and route an event to BVR workers."""
    try:
        event.payload = validate_event_payload(event.event_type, event.payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    svc: EventService = app.state.event_service
    await svc.store_event(
        event_id=event.event_id,
        event_type=event.event_type,
        payload=event.payload,
        correlation_id=event.correlation_id,
        source=event.source,
        priority=event.priority,
        user_id=event.user_id,
    )

    redis = app.state.redis
    await redis.xadd(
        "bvr:events",
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": json.dumps(event.payload),
            "correlation_id": event.correlation_id,
            "priority": event.priority,
        },
    )

    return event


@app.get("/api/v1/events/{event_id}/result", response_model=EventResult)
async def get_event_result(event_id: str):
    """Get the result of an event execution."""
    svc: EventService = app.state.event_service
    row = await svc.get_result(event_id)
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

    return EventResult(
        event_id=str(row["event_id"]),
        status=row["status"],
        result=json.loads(row["result"]) if isinstance(row["result"], str) else row["result"],
        artifact_urls=(
            json.loads(row["artifact_urls"])
            if isinstance(row["artifact_urls"], str)
            else row["artifact_urls"]
        ),
        metrics=(
            json.loads(row["metrics"]) if isinstance(row["metrics"], str) else row["metrics"]
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.post("/api/v1/events/{event_id}/result")
async def post_event_result(event_id: str, result: EventResult):
    """Workers post results back to the API."""
    svc: EventService = app.state.event_service
    await svc.post_result(
        event_id=event_id,
        status=result.status,
        result=result.result,
        artifact_urls=result.artifact_urls,
        metrics=result.metrics,
    )
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Registry endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/registry/workflows", response_model=List[WorkflowDefinition])
async def list_workflows():
    """List all registered workflows."""
    return [
        WorkflowDefinition(
            id="bvr.review.repository",
            namespace="bvr.devops",
            description="Review repository for architecture issues",
            tags=["review", "architecture"],
            kestra_workflow_id="bvr.review.repository",
        ),
        WorkflowDefinition(
            id="bvr.research.topic",
            namespace="bvr.knowledge",
            description="Research topic and produce summary",
            tags=["research", "summary"],
            kestra_workflow_id="bvr.research.topic",
        ),
        WorkflowDefinition(
            id="bvr.achieve.resume-optimization",
            namespace="bvr.career",
            description="Optimize resume for ATS",
            tags=["career", "ats"],
            kestra_workflow_id="bvr.achieve.resume-optimization",
        ),
    ]


@app.post("/api/v1/registry/workers")
async def register_worker(worker: WorkerRegistration):
    """Workers register their capabilities."""
    svc: RegistryService = app.state.registry_service
    await svc.register_worker(
        worker_id=worker.worker_id,
        capabilities=worker.capabilities,
        health_endpoint=worker.health_endpoint,
        version=worker.version,
    )
    return {"status": "registered", "worker_id": worker.worker_id}


@app.get("/api/v1/registry/workers")
async def list_workers():
    """List all registered workers."""
    svc: RegistryService = app.state.registry_service
    return await svc.list_workers()


@app.post("/api/v1/registry/integrations")
async def register_integration(integration: IntegrationManifest):
    """Register a new integration plugin."""
    svc: RegistryService = app.state.registry_service
    await svc.register_integration(
        id=integration.id,
        name=integration.name,
        type_=integration.type,
        version=integration.version,
        capabilities=integration.capabilities,
        status=integration.status,
    )
    return {"status": "registered", "integration_id": integration.id}


@app.get("/api/v1/registry/integrations")
async def list_integrations():
    """List all registered integrations."""
    svc: RegistryService = app.state.registry_service
    return await svc.list_integrations()


# ---------------------------------------------------------------------------
# AI Gateway endpoints
# ---------------------------------------------------------------------------


@app.post("/api/v1/ai-gateway/models")
async def register_model(model: ModelConfig):
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO models
                (id, provider, model_name, capabilities, priority, fallback,
                 cost_per_1k_input, cost_per_1k_output)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                provider           = EXCLUDED.provider,
                model_name         = EXCLUDED.model_name,
                capabilities       = EXCLUDED.capabilities,
                priority           = EXCLUDED.priority,
                fallback           = EXCLUDED.fallback,
                cost_per_1k_input  = EXCLUDED.cost_per_1k_input,
                cost_per_1k_output = EXCLUDED.cost_per_1k_output
            """,
            model.id, model.provider, model.model_name, model.capabilities,
            model.priority, model.fallback, model.cost_per_1k_input, model.cost_per_1k_output,
        )
    return {"status": "registered", "model_id": model.id}


@app.get("/api/v1/ai-gateway/models")
async def list_models():
    pool = app.state.db
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM models ORDER BY priority")
    return [dict(r) for r in rows]


@app.post("/api/v1/ai-gateway/prompts")
async def register_prompt(prompt: PromptTemplate):
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO prompts (id, version, template, variables, model_preference)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                version          = EXCLUDED.version,
                template         = EXCLUDED.template,
                variables        = EXCLUDED.variables,
                model_preference = EXCLUDED.model_preference
            """,
            prompt.id, prompt.version, prompt.template,
            prompt.variables, prompt.model_preference,
        )
    return {"status": "registered", "prompt_id": prompt.id}


# ---------------------------------------------------------------------------
# Policy endpoints
# ---------------------------------------------------------------------------


@app.post("/api/v1/policies")
async def register_policy(policy: PolicyRule):
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO policies (id, rego_path, description, applies_to)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET
                rego_path   = EXCLUDED.rego_path,
                description = EXCLUDED.description,
                applies_to  = EXCLUDED.applies_to
            """,
            policy.id, policy.rego_path, policy.description, policy.applies_to,
        )
    return {"status": "registered", "policy_id": policy.id}


# ---------------------------------------------------------------------------
# Outcome endpoints
# ---------------------------------------------------------------------------


@app.post("/api/v1/outcomes")
async def register_outcome(outcome: OutcomeMetric):
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO outcomes
                (goal_id, description, metric, target, unit, current, workflow_id, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (goal_id) DO UPDATE SET
                description = EXCLUDED.description,
                metric      = EXCLUDED.metric,
                target      = EXCLUDED.target,
                unit        = EXCLUDED.unit,
                current     = EXCLUDED.current,
                workflow_id = EXCLUDED.workflow_id,
                status      = EXCLUDED.status
            """,
            outcome.goal_id, outcome.description, outcome.metric, outcome.target,
            outcome.unit, outcome.current, outcome.workflow_id, outcome.status,
        )
    return {"status": "registered", "goal_id": outcome.goal_id}


@app.get("/api/v1/outcomes")
async def list_outcomes():
    pool = app.state.db
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM outcomes")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Webhook endpoints (Kestra integration)
# ---------------------------------------------------------------------------


class WebhookCallback(BaseModel):
    correlation_id: str
    event_type: str
    status: str
    result: Optional[Dict[str, Any]] = None
    artifact_urls: Optional[List[str]] = None
    metrics: Optional[Dict[str, Any]] = None


@app.post("/api/v1/webhooks/kestra")
async def kestra_webhook(callback: WebhookCallback):
    """Webhook endpoint for workers to notify Kestra of completion."""
    svc: EventService = app.state.event_service
    await svc.post_webhook_result(
        correlation_id=callback.correlation_id,
        status=callback.status,
        result=callback.result,
        artifact_urls=callback.artifact_urls,
        metrics=callback.metrics,
    )

    redis = app.state.redis
    await redis.publish(
        f"bvr:webhook:{callback.correlation_id}",
        json.dumps(callback.model_dump()),
    )

    return {"status": "received", "correlation_id": callback.correlation_id}


@app.get("/api/v1/webhooks/kestra/wait/{correlation_id}")
async def wait_for_webhook(correlation_id: str, timeout: int = 60):
    """Long-polling endpoint for Kestra to wait for worker completion."""
    redis = app.state.redis
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"bvr:webhook:{correlation_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                return {"status": "completed", "result": data}
    except asyncio.TimeoutError:
        return {"status": "timeout", "correlation_id": correlation_id}
    finally:
        await pubsub.unsubscribe(f"bvr:webhook:{correlation_id}")


# ---------------------------------------------------------------------------
# Approval system endpoints
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    approval_id: str
    action: str
    resource: str
    approvers: List[str]
    status: str = "pending"
    created_at: str
    expires_at: str
    approved_by: Optional[str] = None
    denied_by: Optional[str] = None
    approved_at: Optional[str] = None


@app.post("/api/v1/approvals")
async def create_approval(request: ApprovalRequest):
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO approvals
                (approval_id, action, resource, approvers, status, created_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            request.approval_id, request.action, request.resource,
            request.approvers, request.status, request.created_at, request.expires_at,
        )
    return {"status": "created", "approval_id": request.approval_id}


@app.get("/api/v1/approvals/{approval_id}")
async def get_approval(approval_id: str):
    pool = app.state.db
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM approvals WHERE approval_id = $1", approval_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    return dict(row)


@app.post("/api/v1/approvals/{approval_id}/approve")
async def approve_request(approval_id: str, approver: str):
    pool = app.state.db
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM approvals WHERE approval_id = $1", approval_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Approval already processed")
        if approver not in row["approvers"]:
            raise HTTPException(status_code=403, detail="Not an authorized approver")
        await conn.execute(
            """
            UPDATE approvals
            SET status = 'approved', approved_by = $1, approved_at = NOW()
            WHERE approval_id = $2
            """,
            approver, approval_id,
        )
    return {"status": "approved", "approval_id": approval_id}


@app.post("/api/v1/approvals/{approval_id}/deny")
async def deny_request(approval_id: str, approver: str):
    pool = app.state.db
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM approvals WHERE approval_id = $1", approval_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="Approval already processed")
        await conn.execute(
            """
            UPDATE approvals
            SET status = 'denied', denied_by = $1
            WHERE approval_id = $2
            """,
            approver, approval_id,
        )
    return {"status": "denied", "approval_id": approval_id}


@app.get("/api/v1/approvals")
async def list_approvals(status: Optional[str] = None):
    pool = app.state.db
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM approvals WHERE status = $1 ORDER BY created_at DESC", status
            )
        else:
            rows = await conn.fetch("SELECT * FROM approvals ORDER BY created_at DESC")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Capability registry endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/capabilities")
async def list_capabilities():
    from bvr_sdk import get_matcher

    matcher = get_matcher()
    return matcher.list_capabilities()


@app.get("/api/v1/capabilities/{capability_id}/providers")
async def get_capability_providers(capability_id: str):
    from bvr_sdk import CapabilityNotFound, get_matcher

    matcher = get_matcher()
    try:
        providers = matcher.resolve_with_fallback(capability_id)
        return [
            {
                "id": p.id,
                "name": p.name,
                "priority": p.priority,
                "healthy": p.healthy,
                "fallback_enabled": p.fallback_enabled,
                "cost": p.cost,
            }
            for p in providers
        ]
    except CapabilityNotFound:
        raise HTTPException(status_code=404, detail=f"Capability not found: {capability_id}")


@app.post("/api/v1/capabilities/{capability_id}/resolve")
async def resolve_capability(capability_id: str, workflow_id: Optional[str] = None):
    from bvr_sdk import CapabilityNotFound, NoHealthyProvider, get_matcher

    matcher = get_matcher()
    try:
        provider = matcher.resolve(capability_id, workflow_id=workflow_id)
        return {
            "capability": capability_id,
            "provider": {
                "id": provider.id,
                "name": provider.name,
                "priority": provider.priority,
                "healthy": provider.healthy,
            },
        }
    except CapabilityNotFound:
        raise HTTPException(status_code=404, detail=f"Capability not found: {capability_id}")
    except NoHealthyProvider:
        raise HTTPException(status_code=503, detail=f"No healthy providers for: {capability_id}")


@app.post("/api/v1/providers/{provider_id}/health")
async def update_provider_health(provider_id: str, healthy: bool):
    from bvr_sdk import get_matcher

    matcher = get_matcher()
    matcher.update_health(provider_id, healthy)
    return {"status": "updated", "provider_id": provider_id, "healthy": healthy}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "bvr-api", "version": "2.0.0"}


@app.get("/")
async def root():
    return {
        "name": "BVR Nexus API",
        "version": "2.0.0",
        "description": "Application layer for BVR workflow orchestration",
        "endpoints": {
            "events": "/api/v1/events",
            "registry": "/api/v1/registry",
            "ai_gateway": "/api/v1/ai-gateway",
            "policies": "/api/v1/policies",
            "outcomes": "/api/v1/outcomes",
        },
    }
