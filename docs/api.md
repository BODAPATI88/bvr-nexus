# BVR Nexus — API Reference

---

## Authentication

All BVR API endpoints (except `/health`, `/metrics`, and `/`) require a Bearer token.

Two token types are accepted:

| Type | Header | Validation |
|------|--------|-----------|
| Service token | `Authorization: Bearer <BVR_SERVICE_TOKEN>` | Compared against `BVR_SERVICE_TOKEN` env var |
| JWT (Keycloak) | `Authorization: Bearer <jwt>` | Verified against Keycloak JWKS endpoint |

Unauthorized requests return `403`. Invalid tokens return `401`.

---

## BVR API — Base URL: `http://localhost:8000`

### Health

#### `GET /health`
Returns service health status. No authentication required.

**Response 200:**
```json
{"status": "ok", "service": "bvr-api"}
```

#### `GET /metrics`
Returns Prometheus metrics in text format. No authentication required.

---

### Events

#### `POST /api/v1/events`
Submit a workflow event for execution.

**Request body:**
```json
{
  "event_type": "bvr.review.repository",
  "payload": {
    "repo_url": "https://github.com/acme/app"
  },
  "correlation_id": "uuid-string",
  "source": "cli",
  "priority": "normal"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_type` | string | Yes | Workflow type (e.g. `bvr.review.repository`) |
| `payload` | object | Yes | Event-specific data |
| `correlation_id` | string | Yes | Client-assigned correlation ID |
| `source` | string | No | Origin (`cli`, `kestra`, `slack`) |
| `priority` | string | No | `low`, `normal`, `high` (default: `normal`) |

**Response 201:**
```json
{
  "event_id": "uuid",
  "correlation_id": "uuid-string",
  "event_type": "bvr.review.repository",
  "status": "queued",
  "created_at": "2026-07-01T00:00:00Z"
}
```

#### `GET /api/v1/events/{event_id}/result`
Poll for event execution result.

**Response 200 (completed):**
```json
{
  "event_id": "uuid",
  "status": "completed",
  "result": {"...": "worker output"},
  "artifact_urls": ["http://minio/bucket/file"],
  "metrics": {"duration_ms": 1200},
  "completed_at": "2026-07-01T00:01:00Z"
}
```

**Response 200 (pending):**
```json
{"event_id": "uuid", "status": "pending", "result": null}
```

#### `POST /api/v1/events/{event_id}/result`
Internal — called by workers to post execution results. Requires service token.

---

### Registry

#### `POST /api/v1/registry/workers`
Register a worker instance.

**Request body:**
```json
{
  "worker_id": "review-worker-1",
  "capabilities": ["bvr.review.repository"],
  "health_endpoint": "/health",
  "version": "2.0.0"
}
```

#### `GET /api/v1/registry/workers`
List all registered workers.

**Response 200:**
```json
[{"worker_id": "...", "capabilities": [...], "status": "active", ...}]
```

#### `GET /api/v1/registry/workflows`
List all available workflow definitions.

#### `POST /api/v1/registry/integrations`
Register a plugin integration.

**Request body:**
```json
{
  "id": "plugins.ai.claude",
  "name": "Claude",
  "type": "ai",
  "version": "1.0.0",
  "capabilities": ["code_analysis"],
  "status": "active"
}
```

#### `GET /api/v1/registry/integrations`
List all registered integrations.

---

### AI Gateway Registry

#### `POST /api/v1/ai-gateway/models`
Register an AI model in the platform registry.

**Request body:**
```json
{
  "model_id": "claude-sonnet-4",
  "provider": "anthropic",
  "model_name": "claude-sonnet-4-20250514",
  "capabilities": ["code_analysis", "content_generation"],
  "priority": 1,
  "fallback": "gpt-4o",
  "cost_per_1k_input": 0.003,
  "cost_per_1k_output": 0.015
}
```

#### `GET /api/v1/ai-gateway/models`
List all registered models.

#### `POST /api/v1/ai-gateway/prompts`
Register a versioned prompt template.

**Request body:**
```json
{
  "prompt_id": "review-prompt-v1",
  "version": "1.0",
  "template": "Review the following code: {code}",
  "variables": ["code"],
  "model_preference": "claude"
}
```

---

### Policies

#### `POST /api/v1/policies`
Register an OPA policy reference.

**Request body:**
```json
{
  "policy_id": "cost-guardrail",
  "rego_path": "governance/rego/cost.rego",
  "description": "Enforces per-execution cost limits",
  "applies_to": ["bvr.review", "bvr.achieve"]
}
```

---

### Outcomes

#### `POST /api/v1/outcomes`
Register a tracked goal/outcome.

**Request body:**
```json
{
  "goal_id": "goal-improve-coverage",
  "description": "Increase test coverage to 80%",
  "metric": "coverage_pct",
  "target": 80.0,
  "unit": "percent",
  "current": 55.0,
  "workflow_id": "bvr.achieve.coverage",
  "status": "on_track"
}
```

#### `GET /api/v1/outcomes`
List all registered outcomes.

---

### Webhooks

#### `POST /api/v1/webhooks/kestra`
Called by Kestra to trigger a BVR event from a workflow. Identical payload to `POST /api/v1/events`.

#### `GET /api/v1/webhooks/kestra/wait/{correlation_id}`
Long-poll endpoint. Kestra calls this after triggering an event and waits until the worker posts a result. Returns when result is available or after timeout.

**Response 200:**
```json
{"correlation_id": "...", "status": "completed", "result": {...}}
```

---

### Approvals

#### `POST /api/v1/approvals`
Create an approval gate for a pending action.

**Request body:**
```json
{
  "approval_id": "appr-001",
  "action": "deploy",
  "resource": "bvr-api",
  "approvers": ["alice@example.com"],
  "status": "pending",
  "created_at": "2026-07-01T00:00:00Z",
  "expires_at": "2026-07-02T00:00:00Z"
}
```

#### `GET /api/v1/approvals/{approval_id}`
Get approval details.

#### `POST /api/v1/approvals/{approval_id}/approve`
Approve a pending action.

**Request body:** `{"approver": "alice@example.com"}`

#### `POST /api/v1/approvals/{approval_id}/deny`
Deny a pending action.

**Request body:** `{"approver": "alice@example.com"}`

#### `GET /api/v1/approvals`
List approvals, optionally filtered by status.

**Query params:** `?status=pending`

---

### Capabilities

#### `GET /api/v1/capabilities`
List all capabilities declared in `contracts/constitution.yaml`.

#### `GET /api/v1/capabilities/{capability_id}/providers`
List providers for a specific capability, ordered by priority.

#### `POST /api/v1/capabilities/{capability_id}/resolve`
Resolve the best available provider for a capability, accounting for circuit breaker state.

**Request body:** `{"workflow_id": "bvr.review.repository"}`

**Response 200:**
```json
{
  "capability": "code_analysis",
  "resolved_provider": "claude_code",
  "plugin": "plugins.ai.claude",
  "fallback_chain": ["claude_code", "gpt_code", "kimi_code", "ollama_code"]
}
```

#### `POST /api/v1/providers/{provider_id}/health`
Trigger a health check for a specific provider plugin.

---

## AI Gateway — Base URL: `http://localhost:8001`

### Health

#### `GET /health`
Returns AI gateway health. No authentication required.

**Response 200:**
```json
{"status": "ok", "service": "ai-gateway"}
```

---

### Completions

#### `POST /v1/completions`
Request an AI completion. Routes to the best available provider based on capability.

**Request body:**
```json
{
  "capability": "code_analysis",
  "prompt": "Review this function for security issues: ...",
  "model_preference": "claude",
  "max_tokens": 4096,
  "temperature": 0.7,
  "workflow_id": "bvr.review.repository",
  "stream": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `capability` | string | Yes | Capability name from constitution |
| `prompt` | string | Yes | The prompt text |
| `model_preference` | string | No | Preferred provider hint |
| `max_tokens` | integer | No | Maximum tokens (default: 4096) |
| `temperature` | float | No | Sampling temperature (default: 0.7) |
| `workflow_id` | string | No | Used to apply per-workflow constitution overrides |
| `stream` | boolean | No | Use `GET /v1/stream` for SSE streaming instead |

**Response 200:**
```json
{
  "content": "The function has a potential SQL injection vulnerability...",
  "provider": "claude_code",
  "model": "claude-sonnet-4-20250514",
  "usage": {
    "input_tokens": 250,
    "output_tokens": 180
  },
  "cached": false,
  "cost_usd": 0.0034
}
```

**Response 503:** All providers in the fallback chain failed.

---

#### `GET /v1/stream`
SSE streaming endpoint. Same parameters as `POST /v1/completions` passed as query params.

Returns `text/event-stream`. Each event is a JSON token chunk:
```
data: {"content": "The ", "done": false}
data: {"content": "function", "done": false}
data: {"content": "", "done": true, "usage": {...}}
```

---

#### `GET /v1/capabilities`
List all capabilities known to the AI Gateway from `contracts/constitution.yaml`.

#### `GET /v1/providers/{capability_id}`
List providers and their circuit breaker state for a capability.

**Response 200:**
```json
[
  {
    "id": "claude_code",
    "plugin": "plugins.ai.claude",
    "priority": 1,
    "circuit_state": "closed",
    "failure_count": 0
  },
  {
    "id": "gpt_code",
    "plugin": "plugins.ai.gpt",
    "priority": 2,
    "circuit_state": "closed",
    "failure_count": 0
  }
]
```

Circuit states: `closed` (normal), `open` (failing, requests rejected), `half-open` (probing recovery).

---

## Rate Limits

The BVR API enforces rate limiting via middleware:

- **100 requests/minute** per client API key
- **Payload size limit**: 1 MB per request

Requests exceeding the rate limit return `429 Too Many Requests`.

---

## Error Responses

All error responses follow this shape:

```json
{"detail": "human-readable error message"}
```

| HTTP Status | Meaning |
|-------------|---------|
| 400 | Bad request — invalid payload |
| 401 | Invalid or expired token |
| 403 | Missing authentication credentials |
| 404 | Resource not found |
| 422 | Validation error — missing required field or wrong type |
| 429 | Rate limit exceeded |
| 503 | Downstream service unavailable |
