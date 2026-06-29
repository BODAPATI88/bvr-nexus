"""
BVR API Gateway — FastAPI Application Layer
Orchestrates between Kestra (orchestration) and BVR Workers (execution).
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import json
import os
import redis.asyncio as aioredis
import asyncpg
from contextlib import asynccontextmanager

# ── Lifespan ──


# ── Authentication Middleware ──

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate JWT token and return user info."""
    token = credentials.credentials

    # In production: call Keycloak introspection endpoint
    # For now: decode locally with Keycloak public key
    try:
        # Fetch Keycloak public key
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "http://keycloak:8080/realms/bvr",
                timeout=10.0
            )
            if resp.status_code == 200:
                realm_info = resp.json()
                public_key = realm_info.get("public_key", "")
                if public_key:
                    decoded = jwt.decode(
                        token,
                        key=f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----",
                        algorithms=["RS256"],
                        audience="bvr-api",
                        options={"verify_exp": True}
                    )
                    return decoded
    except Exception:
        pass

    # Fallback: check for service token
    if token == os.getenv("BVR_SERVICE_TOKEN", "bvr-service-token"):
        return {"sub": "bvr-service", "roles": ["bvr-service"]}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials"
    )

async def require_role(role: str):
    """Dependency factory for role-based access control."""
    async def _check_role(user: dict = Depends(get_current_user)):
        roles = user.get("roles", [])
        if role not in roles and "bvr-admin" not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {role}"
            )
        return user
    return _check_role

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.redis = await aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True
    )
    app.state.db = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL").replace("+asyncpg","")
    )
    async with app.state.db.acquire() as conn:
        await conn.execute(INIT_SQL)
    yield
    # Shutdown
    await app.state.redis.close()
    await app.state.db.close()

app = FastAPI(
    title="BVR Nexus API",
    description="Application layer for BVR workflow orchestration",
    version="2.0.0",
    lifespan=lifespan,
)



# ── Rate Limiting Middleware ──

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple Redis-based rate limiting."""

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)

        client_id = request.headers.get("X-API-Key", request.client.host)
        redis = request.app.state.redis

        # Check rate limit (100 requests per minute per client)
        key = f"rate_limit:{client_id}"
        current = await redis.get(key)

        if current and int(current) >= 100:
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json"
            )

        await redis.incr(key)
        await redis.expire(key, 60)

        return await call_next(request)

# Add middleware to app
app.add_middleware(RateLimitMiddleware)


# ── Request Logging Middleware ──

import time
import uuid

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with correlation IDs and timing."""

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        start_time = time.time()

        # Log request
        print(f"[REQUEST] {correlation_id} {request.method} {request.url.path} {request.client.host}")

        response = await call_next(request)

        duration = time.time() - start_time

        # Log response
        print(f"[RESPONSE] {correlation_id} {response.status_code} {duration:.3f}s")

        # Add headers
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"

        return response

app.add_middleware(RequestLoggingMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ──

class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    payload: Dict[str, Any]
    correlation_id: str
    source: str = "api"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    priority: str = "normal"  # low, normal, high, critical
    user_id: Optional[str] = None

class EventResult(BaseModel):
    event_id: str
    status: str  # pending, processing, completed, failed
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
    applies_to: List[str]  # event types

class OutcomeMetric(BaseModel):
    goal_id: str
    description: str
    metric: str
    target: float
    unit: str
    current: Optional[float] = None
    workflow_id: str
    status: str = "on_track"

# ── Database Init ──

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

@app.on_event("startup")
async def init_db():
    pool = await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL").replace("+asyncpg","")
    )
    async with pool.acquire() as conn:
        await conn.execute(INIT_SQL)
    await pool.close()

# ── Input Validation Schemas ──

from pydantic import BaseModel, validator, Field
from typing import Dict, Any

class ReviewEventPayload(BaseModel):
    repo_url: str = Field(..., pattern=r'^https?://.*')
    branch: str = Field(default="main", min_length=1, max_length=100)

class ResearchEventPayload(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    depth: str = Field(default="standard", pattern=r'^(quick|standard|deep)$')

class AchieveEventPayload(BaseModel):
    resume_content: str = Field(..., min_length=50, max_length=50000)
    target_role: str = Field(default="Software Engineer", min_length=2, max_length=100)

EVENT_PAYLOAD_SCHEMAS = {
    "review.repository": ReviewEventPayload,
    "research.topic": ResearchEventPayload,
    "achieve.resume-optimization": AchieveEventPayload,
}

def validate_event_payload(event_type: str, payload: dict) -> dict:
    """Validate event payload against known schema."""
    schema_class = EVENT_PAYLOAD_SCHEMAS.get(event_type)
    if schema_class:
        validated = schema_class(**payload)
        return validated.dict()
    return payload  # Unknown event types pass through (extensibility)

# ── Event Endpoints ──

@app.post("/api/v1/events", response_model=EventEnvelope)
async def emit_event(
    event: EventEnvelope,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
):
    """
    Receive an event from Kestra (or any source), store it,
    and route it to the appropriate worker via Redis Streams.
    """
    # Validate payload
    try:
        event.payload = validate_event_payload(event.event_type, event.payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    
    # Store event
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (event_id, event_type, payload, correlation_id, source, priority, user_id, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
            """,
            event.event_id, event.event_type, json.dumps(event.payload),
            event.correlation_id, event.source, event.priority, event.user_id
        )

    # Publish to Redis Stream for worker consumption
    redis = app.state.redis
    await redis.xadd(
        "bvr:events",
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": json.dumps(event.payload),
            "correlation_id": event.correlation_id,
            "priority": event.priority,
        }
    )

    return event

@app.get("/api/v1/events/{event_id}/result", response_model=EventResult)
async def get_event_result(event_id: str):
    """Get the result of an event execution."""
    pool = app.state.db
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.event_id, e.status, r.result, r.artifact_urls, r.metrics, e.timestamp as created_at, r.updated_at
            FROM events e
            LEFT JOIN event_results r ON e.event_id = r.event_id
            WHERE e.event_id = $1
            """,
            event_id
        )

    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

    return EventResult(
        event_id=str(row["event_id"]),
        status=row["status"],
        result=row["result"],
        artifact_urls=row["artifact_urls"],
        metrics=row["metrics"],
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )

@app.post("/api/v1/events/{event_id}/result")
async def post_event_result(event_id: str, result: EventResult):
    """Workers post results back to the API."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO event_results (event_id, result, artifact_urls, metrics, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (event_id) DO UPDATE SET
                result = EXCLUDED.result,
                artifact_urls = EXCLUDED.artifact_urls,
                metrics = EXCLUDED.metrics,
                updated_at = NOW()
            """,
            event_id, json.dumps(result.result) if result.result else None,
            json.dumps(result.artifact_urls) if result.artifact_urls else None,
            json.dumps(result.metrics) if result.metrics else None
        )
        await conn.execute(
            "UPDATE events SET status = $1 WHERE event_id = $2",
            result.status, event_id
        )
    return {"status": "ok"}

# ── Registry Endpoints ──

@app.get("/api/v1/registry/workflows", response_model=List[WorkflowDefinition])
async def list_workflows():
    """List all registered workflows."""
    return [
        WorkflowDefinition(
            id="bvr.review.repository",
            namespace="bvr.devops",
            description="Review repository for architecture issues",
            tags=["review", "architecture"],
            kestra_workflow_id="bvr.review.repository"
        ),
        WorkflowDefinition(
            id="bvr.research.topic",
            namespace="bvr.knowledge",
            description="Research topic and produce summary",
            tags=["research", "summary"],
            kestra_workflow_id="bvr.research.topic"
        ),
        WorkflowDefinition(
            id="bvr.achieve.resume-optimization",
            namespace="bvr.career",
            description="Optimize resume for ATS",
            tags=["career", "ats"],
            kestra_workflow_id="bvr.achieve.resume-optimization"
        ),
    ]

@app.post("/api/v1/registry/workers")
async def register_worker(worker: WorkerRegistration):
    """Workers register their capabilities."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workers (worker_id, capabilities, health_endpoint, version, last_seen, status)
            VALUES ($1, $2, $3, $4, NOW(), 'active')
            ON CONFLICT (worker_id) DO UPDATE SET
                capabilities = EXCLUDED.capabilities,
                health_endpoint = EXCLUDED.health_endpoint,
                version = EXCLUDED.version,
                last_seen = NOW()
            """,
            worker.worker_id, worker.capabilities, worker.health_endpoint, worker.version
        )
    return {"status": "registered", "worker_id": worker.worker_id}

@app.get("/api/v1/registry/workers")
async def list_workers():
    """List all registered workers."""
    pool = app.state.db
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM workers")
    return [dict(r) for r in rows]

@app.post("/api/v1/registry/integrations")
async def register_integration(integration: IntegrationManifest):
    """Register a new integration plugin."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO integrations (id, name, type, version, capabilities, status)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                version = EXCLUDED.version,
                capabilities = EXCLUDED.capabilities,
                status = EXCLUDED.status
            """,
            integration.id, integration.name, integration.type,
            integration.version, integration.capabilities, integration.status
        )
    return {"status": "registered", "integration_id": integration.id}

@app.get("/api/v1/registry/integrations")
async def list_integrations():
    """List all registered integrations."""
    pool = app.state.db
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM integrations")
    return [dict(r) for r in rows]

# ── AI Gateway Endpoints ──

@app.post("/api/v1/ai-gateway/models")
async def register_model(model: ModelConfig):
    """Register an AI model provider."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO models (id, provider, model_name, capabilities, priority, fallback, cost_per_1k_input, cost_per_1k_output)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                provider = EXCLUDED.provider,
                model_name = EXCLUDED.model_name,
                capabilities = EXCLUDED.capabilities,
                priority = EXCLUDED.priority,
                fallback = EXCLUDED.fallback,
                cost_per_1k_input = EXCLUDED.cost_per_1k_input,
                cost_per_1k_output = EXCLUDED.cost_per_1k_output
            """,
            model.id, model.provider, model.model_name, model.capabilities,
            model.priority, model.fallback, model.cost_per_1k_input, model.cost_per_1k_output
        )
    return {"status": "registered", "model_id": model.id}

@app.get("/api/v1/ai-gateway/models")
async def list_models():
    """List all registered AI models."""
    pool = app.state.db
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM models ORDER BY priority")
    return [dict(r) for r in rows]

@app.post("/api/v1/ai-gateway/prompts")
async def register_prompt(prompt: PromptTemplate):
    """Register a prompt template."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO prompts (id, version, template, variables, model_preference)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                version = EXCLUDED.version,
                template = EXCLUDED.template,
                variables = EXCLUDED.variables,
                model_preference = EXCLUDED.model_preference
            """,
            prompt.id, prompt.version, prompt.template, prompt.variables, prompt.model_preference
        )
    return {"status": "registered", "prompt_id": prompt.id}

# ── Policy Endpoints ──

@app.post("/api/v1/policies")
async def register_policy(policy: PolicyRule):
    """Register a policy rule."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO policies (id, rego_path, description, applies_to)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET
                rego_path = EXCLUDED.rego_path,
                description = EXCLUDED.description,
                applies_to = EXCLUDED.applies_to
            """,
            policy.id, policy.rego_path, policy.description, policy.applies_to
        )
    return {"status": "registered", "policy_id": policy.id}

# ── Outcome Endpoints ──

@app.post("/api/v1/outcomes")
async def register_outcome(outcome: OutcomeMetric):
    """Register a measurable outcome goal."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO outcomes (goal_id, description, metric, target, unit, current, workflow_id, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (goal_id) DO UPDATE SET
                description = EXCLUDED.description,
                metric = EXCLUDED.metric,
                target = EXCLUDED.target,
                unit = EXCLUDED.unit,
                current = EXCLUDED.current,
                workflow_id = EXCLUDED.workflow_id,
                status = EXCLUDED.status
            """,
            outcome.goal_id, outcome.description, outcome.metric, outcome.target,
            outcome.unit, outcome.current, outcome.workflow_id, outcome.status
        )
    return {"status": "registered", "goal_id": outcome.goal_id}

@app.get("/api/v1/outcomes")
async def list_outcomes():
    """List all measurable outcomes."""
    pool = app.state.db
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM outcomes")
    return [dict(r) for r in rows]

# ── Health ──



# ── Webhook Callback Endpoints (for Kestra integration) ──

class WebhookCallback(BaseModel):
    correlation_id: str
    event_type: str
    status: str
    result: Optional[Dict[str, Any]] = None
    artifact_urls: Optional[List[str]] = None
    metrics: Optional[Dict[str, Any]] = None

@app.post("/api/v1/webhooks/kestra")
async def kestra_webhook(callback: WebhookCallback):
    """
    Webhook endpoint for workers to notify Kestra of completion.
    Workers call this instead of Kestra polling.
    """
    # Store result
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO event_results (event_id, result, artifact_urls, metrics, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (event_id) DO UPDATE SET
                result = EXCLUDED.result,
                artifact_urls = EXCLUDED.artifact_urls,
                metrics = EXCLUDED.metrics,
                updated_at = NOW()
            """,
            callback.correlation_id, 
            json.dumps(callback.result) if callback.result else None,
            json.dumps(callback.artifact_urls) if callback.artifact_urls else None,
            json.dumps(callback.metrics) if callback.metrics else None
        )
        await conn.execute(
            "UPDATE events SET status = $1 WHERE correlation_id = $2",
            callback.status, callback.correlation_id
        )

    # Notify any waiting Kestra workflows via Redis pub/sub
    redis = app.state.redis
    await redis.publish(
        f"bvr:webhook:{callback.correlation_id}",
        json.dumps(callback.model_dump())
    )

    return {"status": "received", "correlation_id": callback.correlation_id}

@app.get("/api/v1/webhooks/kestra/wait/{correlation_id}")
async def wait_for_webhook(correlation_id: str, timeout: int = 60):
    """
    Long-polling endpoint for Kestra to wait for worker completion.
    Returns immediately when webhook is received, or times out.
    """
    redis = app.state.redis
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"bvr:webhook:{correlation_id}")

    try:
        # Wait for message with timeout
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                return {"status": "completed", "result": data}
    except asyncio.TimeoutError:
        return {"status": "timeout", "correlation_id": correlation_id}
    finally:
        await pubsub.unsubscribe(f"bvr:webhook:{correlation_id}")



# ── Approval System Endpoints ──

class ApprovalRequest(BaseModel):
    approval_id: str
    action: str
    resource: str
    approvers: List[str]
    status: str = "pending"  # pending, approved, denied, expired
    created_at: str
    expires_at: str
    approved_by: Optional[str] = None
    denied_by: Optional[str] = None
    approved_at: Optional[str] = None

@app.post("/api/v1/approvals")
async def create_approval(request: ApprovalRequest):
    """Create an approval request for human-in-the-loop gates."""
    pool = app.state.db
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO approvals (approval_id, action, resource, approvers, status, created_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            request.approval_id, request.action, request.resource,
            request.approvers, request.status, request.created_at, request.expires_at
        )
    return {"status": "created", "approval_id": request.approval_id}

@app.get("/api/v1/approvals/{approval_id}")
async def get_approval(approval_id: str):
    """Get approval status by ID."""
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
    """Approve a pending request."""
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
            approver, approval_id
        )
    return {"status": "approved", "approval_id": approval_id}

@app.post("/api/v1/approvals/{approval_id}/deny")
async def deny_request(approval_id: str, approver: str):
    """Deny a pending request."""
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
            approver, approval_id
        )
    return {"status": "denied", "approval_id": approval_id}

@app.get("/api/v1/approvals")
async def list_approvals(status: Optional[str] = None):
    """List all approval requests, optionally filtered by status."""
    pool = app.state.db
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM approvals WHERE status = $1 ORDER BY created_at DESC",
                status
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM approvals ORDER BY created_at DESC"
            )
    return [dict(r) for r in rows]



# ── Capability Registry Endpoints ──

@app.get("/api/v1/capabilities")
async def list_capabilities():
    """List all capabilities from the Constitution."""
    from bvr_sdk import get_matcher
    matcher = get_matcher()
    return matcher.list_capabilities()

@app.get("/api/v1/capabilities/{capability_id}/providers")
async def get_capability_providers(capability_id: str):
    """Get all providers for a capability, ordered by priority."""
    from bvr_sdk import get_matcher, CapabilityNotFound
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
    """Resolve a capability to the best provider (for testing)."""
    from bvr_sdk import get_matcher, CapabilityNotFound, NoHealthyProvider
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
            }
        }
    except CapabilityNotFound:
        raise HTTPException(status_code=404, detail=f"Capability not found: {capability_id}")
    except NoHealthyProvider:
        raise HTTPException(status_code=503, detail=f"No healthy providers for: {capability_id}")

@app.post("/api/v1/providers/{provider_id}/health")
async def update_provider_health(provider_id: str, healthy: bool):
    """Update health status of a provider (called by health checker)."""
    from bvr_sdk import get_matcher
    matcher = get_matcher()
    matcher.update_health(provider_id, healthy)
    return {"status": "updated", "provider_id": provider_id, "healthy": healthy}

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
        }
    }
