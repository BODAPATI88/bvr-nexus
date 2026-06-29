# BVR NEXUS — Revised Integrated Architecture v2.0
## Declarative Workflow Orchestration Platform (Production-Ready)

> **Strategy**: Kestra orchestrates. Your Event Platform executes. FastAPI owns the API.  
> **Philosophy**: Orchestration ≠ Application. Business logic lives in your services.

---

## Executive Summary

This revision corrects the biggest architectural risk from v1: **letting Kestra absorb business logic**. Instead, Kestra is strictly an orchestration layer. Your own **Event Platform** (Event Envelope → Router → Registry → Workers) is the execution runtime. A **FastAPI Gateway** sits between users and the platform. An **AI Gateway** abstracts all model providers. Everything is discoverable through a **Platform Registry**.

**Removed from v1**: Weaviate, ClickHouse, Kafka, Kong (overlapping), LangGraph as center.  
**Added in v2**: FastAPI Gateway, BVR Event Bus, BVR SDK, Platform Registry, AI Gateway, Plugin System, pgvector.

---

## Core Principle: Separation of Concerns

```
┌─────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION          │  APPLICATION          │  DATA        │
│  (Kestra)               │  (Your Services)      │  (Stores)    │
│                         │                       │              │
│  • Schedule             │  • Business Logic     │  • Postgres  │
│  • Retry                │  • AI Reasoning       │  • pgvector  │
│  • Approval Gates       │  • Event Routing      │  • Redis     │
│  • Execution Graphs     │  • Worker Registry    │  • MinIO     │
│  • SLA Monitoring       │  • Plugin Loading     │              │
│  • Notifications        │  • Cost Tracking      │              │
└─────────────────────────────────────────────────────────────────┘
```

**Kestra never contains business logic.** It calls your BVR API via HTTP. Your API emits events. Your workers execute. Kestra waits for completion and continues the graph.

---

## Revised Layer Architecture

### L0. USER INTERFACE LAYER
| Component | Implementation | Notes |
|-----------|---------------|-------|
| **BVR CLI** | Typer + Rich | Calls FastAPI Gateway, not Kestra directly |
| **Web UI** | FastAPI + Jinja2 / React SPA | Your own UI, not Kestra's |
| **VS Code Extension** | TypeScript | Calls BVR API Gateway |
| **Slack Bot** | Bolt + FastAPI | Event-driven via BVR Event Bus |
| **API Gateway** | **Traefik** only | Ingress + TLS + routing. Kong removed. |

### L1. ORCHESTRATION LAYER (Kestra — Orchestration Only)
| Component | Kestra Role | What It Does NOT Do |
|-----------|-------------|---------------------|
| **Intent Parser** | Trigger webhook | Kestra receives intent, passes to BVR API |
| **Workflow Resolver** | Git-synced YAML | Maps intent to workflow ID |
| **Planner** | DAG builder | Builds execution graph |
| **Capability Matcher** | Plugin check | Verifies BVR API endpoint exists |
| **Policy Evaluator** | Pre-exec webhook | Calls OPA via BVR API |
| **Dispatcher** | HTTP task | POSTs to BVR API, does NOT run business logic |
| **Registry Layer** | Git namespaces | Workflow definitions only |

**Kestra workflows contain only:**
- Webhook triggers
- HTTP calls to BVR API
- Wait conditions
- Retry logic
- Approval gates
- Notifications
- SLA checks

### L2. EXECUTION LAYER (BVR Event Platform — Your Code)
| Component | Implementation | Responsibility |
|-----------|---------------|----------------|
| **Event Envelope** | Pydantic models | Standardized event schema |
| **Router** | FastAPI + Redis Streams | Routes events to correct worker |
| **Registry** | PostgreSQL + FastAPI | Discovers workers, integrations, models |
| **Workers** | Python async (anyio) | Execute business logic |
| **Step Executor** | BVR Worker Pool | Docker or process-based |
| **Context Manager** | Redis KV + BVR SDK | Cross-step state |
| **Retry & Timeout** | BVR SDK (tenacity) | Application-level retry |
| **Result Aggregator** | Pydantic validation | Schema enforcement |
| **Artifact Generator** | Jinja2 + WeasyPrint | Report generation |

### L3. INTEGRATION LAYER (Plugin System)
| Category | BVR Plugin | Manifest |
|----------|-----------|----------|
| **AI / LLM** | AI Gateway | `manifest.yaml`, `schema.yaml`, `worker.py` |
| **DevOps / Infra** | Azure, K8s, Docker, TF | Auto-loaded from `plugins/devops/` |
| **Code & Data** | GitHub, GitLab, DBs | Auto-loaded from `plugins/code/` |
| **Productivity** | Slack, Gmail, Notion | Auto-loaded from `plugins/productivity/` |

Each plugin exposes:
- `manifest.yaml` — name, version, capabilities, dependencies
- `schema.yaml` — input/output contracts
- `permissions.yaml` — required permissions
- `health.py` — health check endpoint
- `worker.py` — execution logic

### L4. DATA & STATE LAYER (Simplified)
| Component | Implementation | Why |
|-----------|---------------|-----|
| **Artifact Store** | MinIO | S3-compatible, proven |
| **State Store** | PostgreSQL | Kestra + BVR state |
| **Knowledge Base** | **PostgreSQL + pgvector** | One DB, one backup, one replication |
| **Cache** | Redis | Temporary data + lightweight messaging |
| **Audit Log** | PostgreSQL + Loki | Structured logs in PG, raw logs in Loki |

**Removed**: Weaviate (use pgvector), ClickHouse (Loki is enough), Kafka (Redis Streams).

### L5. GOVERNANCE LAYER
| Component | Implementation | Notes |
|-----------|---------------|-------|
| **Policy Engine** | OPA | Pre/post execution via BVR API |
| **Approval Engine** | Kestra Pause + BVR UI | Human-in-the-loop |
| **Security & Access** | Keycloak + Vault | RBAC, SSO, secrets |
| **Compliance** | OPA + BVR SDK | Data residency, PII checks |
| **Verifier** | Pydantic + OPA | Output validation |

### L6. OBSERVABILITY LAYER
| Component | Implementation | Notes |
|-----------|---------------|-------|
| **Telemetry** | OpenTelemetry (OTel) | Auto-instrumented via BVR SDK |
| **Metrics** | Prometheus | Time-series |
| **Dashboards** | Grafana | KPIs, workflow health |
| **Alerting** | Alertmanager + Grafana | Thresholds, anomalies |
| **Cost Tracking** | BVR SDK + OpenCost | Per-workflow cost attribution |

---

## Revised Data Flow

```
User Intent
    ↓
Traefik (Ingress + TLS)
    ↓
FastAPI Gateway (Auth, Rate Limit, Validation)
    ↓
Kestra (Orchestration)
    ↓
HTTP POST /api/v1/events (BVR API)
    ↓
Event Envelope (Pydantic validated)
    ↓
Router (Redis Streams)
    ↓
Registry Lookup (PostgreSQL)
    ↓
Worker (Python async)
    ↓
AI Gateway (if LLM needed)
    ↓
Claude / GPT / Gemini / Kimi / Ollama
    ↓
Result Event
    ↓
Redis Streams
    ↓
Kestra (continues workflow graph)
    ↓
Artifact Store (MinIO)
    ↓
Notification (Slack/Email)
```

---

## The BVR SDK

Every worker imports the same SDK. This is the contract layer:

```python
# bvr_sdk/__init__.py
from .events import EventEnvelope, emit_event, subscribe
from .auth import get_token, verify_permission
from .storage import upload_artifact, download_artifact
from .ai import ai_gateway_call, track_tokens
from .telemetry import trace_span, log_metric, log_event
from .retry import with_retry, with_timeout
from .policy import check_policy, require_approval
from .registry import register_worker, discover_integration

__all__ = [
    "EventEnvelope", "emit_event", "subscribe",
    "get_token", "verify_permission",
    "upload_artifact", "download_artifact",
    "ai_gateway_call", "track_tokens",
    "trace_span", "log_metric", "log_event",
    "with_retry", "with_timeout",
    "check_policy", "require_approval",
    "register_worker", "discover_integration",
]
```

---

## The AI Gateway

Instead of calling providers directly, all LLM calls go through the AI Gateway:

```yaml
# ai-gateway.yaml
providers:
  claude:
    model: claude-sonnet-4
    priority: 1
    fallback: gpt
    rate_limit: 100/min
    cost_per_1k: 0.003

  gpt:
    model: gpt-5
    priority: 2
    fallback: kimi
    rate_limit: 200/min
    cost_per_1k: 0.0025

  kimi:
    model: kimi-k2
    priority: 3
    fallback: ollama
    rate_limit: 500/min
    cost_per_1k: 0.001

  ollama:
    model: llama3.3
    priority: 4
    local: true
    cost_per_1k: 0.0

features:
  fallback: true
  cost_tracking: true
  caching: true
  routing_by_capability: true
  provider_independence: true
```

**Benefits:**
- Fallback on provider failure
- Unified cost tracking
- Response caching
- Route by capability (code, reasoning, creative)
- Swap providers without changing workers

---

## The Platform Registry

Everything is discoverable:

```yaml
# platform-registry.yaml
workflows:
  - id: bvr.review.repository
    namespace: bvr.devops
    source: git://github.com/bvr/workflows#review/repository.yml

workers:
  - id: code-analyzer
    capabilities: [analyze_code, scan_repo, generate_report]
    health_endpoint: /health
    last_seen: 2026-06-27T10:00:00Z

integrations:
  - id: github
    type: code
    status: connected
    health: ok

models:
  - id: claude-sonnet-4
    provider: anthropic
    capabilities: [reasoning, code, analysis]
    cost_per_1k_input: 0.003
    cost_per_1k_output: 0.015

prompts:
  - id: architecture-review
    version: 1.2
    template: "Review this codebase for..."

policies:
  - id: cost-guardrail
    rego: policies/cost.rego

tools:
  - id: terraform-plan
    plugin: devops/terraform
    schema: schemas/terraform-plan.json
```

---

## Technology Stack (Revised)

| Layer | Component | License | Maturity | Role |
|-------|-----------|---------|----------|------|
| Orchestration | **Kestra** | Apache 2.0 | Production | Schedules, retries, approvals, graphs |
| API Gateway | **Traefik** | MIT | Production | Ingress, TLS, routing |
| Application API | **FastAPI** | MIT | Production | BVR API layer |
| Event Bus | **Redis Streams** | BSD | Production | Lightweight messaging |
| State | **PostgreSQL** | PostgreSQL | Production | Primary data store |
| Vector Search | **pgvector** (PostgreSQL ext) | MIT | Production | Knowledge base |
| Cache | **Redis** | BSD | Production | Cache + streams |
| Artifacts | **MinIO** | AGPL v3 | Production | S3-compatible storage |
| AI Gateway | **Custom FastAPI** | MIT | BVR-specific | Abstracts LLM providers |
| Workers | **Python async (anyio)** | MIT | Standard | Business logic execution |
| Policy | **OPA** | Apache 2.0 | Enterprise | Policy as code |
| Auth | **Keycloak** | Apache 2.0 | Enterprise | SSO, RBAC |
| Secrets | **Vault** | MPL 2.0 | Enterprise | Secret management |
| Observability | **OpenTelemetry + Prometheus + Grafana** | Apache 2.0 | Cloud-native | Metrics, traces, logs |
| Logs | **Loki** | AGPL v3 | Production | Log aggregation |
| Local LLM | **Ollama** | MIT | Production | Local model serving |

**Removed from v1**: Weaviate, ClickHouse, Kafka, Kong, LangGraph as center.

---

## File Structure (Revised)

```
bvr-nexus/
├── docker-compose.yml              # Full stack (simplified)
├── README.md
├── start.sh
│
├── api/                            # FastAPI Gateway (Your Application)
│   ├── main.py                     # FastAPI app, event endpoints
│   ├── routers/
│   │   ├── events.py               # POST /events, GET /events/:id
│   │   ├── workflows.py            # Workflow registry CRUD
│   │   ├── workers.py              # Worker registry & health
│   │   ├── integrations.py         # Integration management
│   │   ├── models.py               # AI Gateway model registry
│   │   ├── prompts.py              # Prompt registry
│   │   ├── policies.py             # Policy evaluation
│   │   └── outcomes.py             # Measurable outcomes
│   ├── services/
│   │   ├── event_router.py         # Redis Streams router
│   │   ├── registry.py             # Platform registry logic
│   │   ├── ai_gateway.py           # AI Gateway service
│   │   └── cost_tracker.py         # Cost attribution
│   └── dependencies.py             # FastAPI deps (auth, db)
│
├── bvr-sdk/                        # BVR SDK (pip install bvr-sdk)
│   ├── bvr_sdk/
│   │   ├── __init__.py
│   │   ├── events.py               # EventEnvelope, emit, subscribe
│   │   ├── auth.py                 # Token, permission checks
│   │   ├── storage.py              # MinIO artifact operations
│   │   ├── ai.py                   # AI Gateway client
│   │   ├── telemetry.py            # OTel tracing, metrics
│   │   ├── retry.py                # Tenacity wrappers
│   │   ├── policy.py               # OPA client
│   │   └── registry.py             # Worker registration, discovery
│   ├── setup.py
│   └── tests/
│
├── workers/                        # BVR Workers (Business Logic)
│   ├── review/
│   │   ├── code_analyzer.py        # Analyze code structure
│   │   └── report_generator.py     # Generate review reports
│   ├── architect/
│   │   └── design_validator.py     # Validate architecture designs
│   ├── research/
│   │   └── topic_synthesizer.py    # Research & summarize
│   ├── achieve/
│   │   └── resume_optimizer.py     # ATS optimization
│   └── base.py                     # Base worker class (uses BVR SDK)
│
├── plugins/                        # Plugin System
│   ├── ai/
│   │   ├── claude/
│   │   │   ├── manifest.yaml
│   │   │   ├── schema.yaml
│   │   │   ├── permissions.yaml
│   │   │   ├── health.py
│   │   │   └── worker.py
│   │   ├── gpt/
│   │   ├── kimi/
│   │   └── ollama/
│   ├── devops/
│   │   ├── azure/
│   │   ├── kubernetes/
│   │   ├── docker/
│   │   └── terraform/
│   ├── code/
│   │   ├── github/
│   │   └── gitlab/
│   └── productivity/
│       ├── slack/
│       ├── gmail/
│       └── notion/
│
├── kestra-workflows/               # Kestra Orchestration (No Business Logic)
│   ├── review/
│   │   └── repository.yml          # HTTP calls to BVR API only
│   ├── architect/
│   ├── research/
│   └── achieve/
│
├── contracts/                      # YAML Constitution (unchanged)
│   ├── workflow.yaml
│   ├── operation.yaml
│   ├── integration.yaml
│   ├── execution.yaml
│   ├── result.yaml
│   ├── artifact.yaml
│   ├── entity.yaml
│   └── goal.yaml
│
├── governance/                     # OPA Policies
│   └── rego/
│       ├── bvr.rego                # Main policy
│       ├── cost.rego               # Cost guardrails
│       └── data_residency.rego     # Compliance
│
├── gateway/                        # Traefik Config
│   └── traefik.yml
│
└── observability/                  # Prometheus + Grafana + Loki
    ├── prometheus.yml
    ├── loki-config.yml
    └── dashboards/
        └── bvr-overview.json
```

---

## Example Kestra Workflow (Revised — No Business Logic)

```yaml
id: bvr.review.repository
namespace: bvr.devops

description: |
  Orchestrate repository review.
  Kestra does NOT analyze code. It calls BVR API.

tasks:
  - id: notify_start
    type: io.kestra.plugin.core.debug.Echo
    format: "Starting review for {{ inputs.repo_url }}"

  - id: call_bvr_api
    type: io.kestra.plugin.http.Request
    uri: "http://bvr-api:8000/api/v1/events"
    method: POST
    contentType: application/json
    body: |
      {
        "event_type": "review.repository",
        "payload": {
          "repo_url": "{{ inputs.repo_url }}",
          "branch": "{{ inputs.branch }}"
        },
        "correlation_id": "{{ execution.id }}",
        "source": "kestra"
      }
    headers:
      Authorization: "Bearer {{ secret('BVR_API_TOKEN') }}"

  - id: wait_for_result
    type: io.kestra.plugin.core.flow.Pause
    delay: PT30S
    # In production: use webhook callback from BVR API

  - id: fetch_result
    type: io.kestra.plugin.http.Request
    uri: "http://bvr-api:8000/api/v1/events/{{ outputs.call_bvr_api.body.event_id }}/result"
    method: GET
    headers:
      Authorization: "Bearer {{ secret('BVR_API_TOKEN') }}"

  - id: validate_output
    type: io.kestra.plugin.core.debug.Echo
    format: "Review complete. Score: {{ outputs.fetch_result.body.score }}"

  - id: notify_slack
    type: io.kestra.plugin.notifications.slack.SlackIncomingWebhook
    url: "{{ secret('SLACK_WEBHOOK') }}"
    payload: |
      {
        "text": "Review complete: {{ inputs.repo_url }}\nScore: {{ outputs.fetch_result.body.score }}/100"
      }

sla:
  - id: completion_time
    type: io.kestra.plugin.core.condition.MaxDuration
    duration: PT20M

triggers:
  - id: webhook
    type: io.kestra.plugin.core.trigger.Webhook
    key: bvr-review-repo
```

---

## Example BVR Worker (Uses SDK)

```python
# workers/review/code_analyzer.py
from bvr_sdk import (
    EventEnvelope, emit_event, trace_span,
    ai_gateway_call, upload_artifact, check_policy
)
from workers.base import BaseWorker

class CodeAnalyzerWorker(BaseWorker):
    capabilities = ["analyze_code", "scan_repo"]

    @trace_span("code_analyzer.analyze")
    async def handle(self, event: EventEnvelope):
        repo_url = event.payload["repo_url"]
        branch = event.payload.get("branch", "main")

        # Policy check
        await check_policy("review.allowed", {"target": repo_url})

        # Clone repo (via plugin)
        repo = await self.plugin("github").clone(repo_url, branch)

        # Analyze with LLM via AI Gateway
        findings = await ai_gateway_call(
            capability="code_analysis",
            prompt=f"Analyze architecture of {repo.path}",
            model_preference="claude"
        )

        # Generate artifact
        report = await self.generate_report(findings)
        artifact_url = await upload_artifact(
            data=report,
            path=f"reports/{event.correlation_id}/review.md"
        )

        # Emit result event
        await emit_event(
            event_type="review.repository.completed",
            payload={
                "score": findings.score,
                "artifact_url": artifact_url,
                "findings": findings.items
            },
            correlation_id=event.correlation_id
        )
```

---

## Deployment Architecture (Revised)

```
┌─────────────────────────────────────────────────────────────────┐
│                         INGRESS                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Traefik (TLS termination, rate limit, routing)        │   │
│  └────────────────────┬────────────────────────────────────┘   │
└───────────────────────┼────────────────────────────────────────┘
                        │
┌───────────────────────┼────────────────────────────────────────┐
│                   APPLICATION LAYER                              │
│  ┌────────────────────┴────────────────────────────────────┐   │
│  │  FastAPI Gateway (Auth, Validation, Rate Limiting)      │   │
│  │  • /api/v1/events      • /api/v1/workflows             │   │
│  │  • /api/v1/workers     • /api/v1/integrations         │   │
│  │  • /api/v1/models      • /api/v1/prompts               │   │
│  │  • /api/v1/policies    • /api/v1/outcomes              │   │
│  └────────────────────┬────────────────────────────────────┘   │
└───────────────────────┼────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌───────┴───────┐ ┌─────┴───────┐ ┌────┴────────────┐
│  Kestra       │ │ BVR Event   │ │  AI Gateway     │
│  (Orchestrate)│ │ Bus (Redis) │ │  (FastAPI)      │
│               │ │             │ │                 │
│  • Schedule   │ │  • Route    │ │  • Fallback     │
│  • Retry      │ │  • Queue    │ │  • Cost Track   │
│  • Approve    │ │  • Persist  │ │  • Cache        │
│  • Graph      │ │             │ │  • Route        │
└───────┬───────┘ └─────┬───────┘ └─────────────────┘
        │               │
        │       ┌───────┴───────┐
        │       │  BVR Workers  │
        │       │  (Python)     │
        │       │               │
        │       │  • Business   │
        │       │    Logic      │
        │       │  • Plugins    │
        │       │  • AI Calls   │
        │       └───────────────┘
        │               │
        └───────────────┘
                        │
┌───────────────────────┼────────────────────────────────────────┐
│                   DATA LAYER                                     │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌────────────────────┐ │
│  │ Postgres│ │  Redis  │ │  MinIO   │ │  Loki              │ │
│  │ +       │ │ (Cache  │ │ (S3      │ │ (Log               │ │
│  │ pgvector│ │  +      │ │  Artif-  │ │  Aggregation)      │ │
│  │         │ │ Streams)│ │  acts)   │ │                    │ │
│  └─────────┘ └─────────┘ └──────────┘ └────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                        │
┌───────────────────────┼────────────────────────────────────────┐
│                   GOVERNANCE                                   │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌────────────────────┐ │
│  │  OPA    │ │ Keycloak│ │  Vault   │ │  BVR SDK           │ │
│  │ (Policy)│ │ (Auth)  │ │(Secrets) │ │  (Policy Client)   │ │
│  └─────────┘ └─────────┘ └──────────┘ └────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                        │
┌───────────────────────┼────────────────────────────────────────┐
│                   OBSERVABILITY                                │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌────────────────────┐ │
│  │Prometheus│ │ Grafana │ │  Jaeger  │ │ OpenCost           │ │
│  │(Metrics) │ │(Dash)   │ │ (Traces) │ │ (Cost Tracking)    │ │
│  └─────────┘ └─────────┘ └──────────┘ └────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

---

## Implementation Roadmap (Revised)

### Phase 1: Foundation (Week 1-2)
- Deploy PostgreSQL + pgvector, Redis, MinIO
- Build FastAPI Gateway skeleton
- Deploy Kestra (orchestration only)
- Deploy Traefik
- Set up BVR SDK scaffolding

### Phase 2: Event Platform (Week 3-4)
- Build Event Envelope (Pydantic)
- Implement Redis Streams router
- Build Worker base class
- Create Platform Registry (PostgreSQL)
- Deploy OPA + Keycloak + Vault

### Phase 3: AI Gateway (Week 5-6)
- Build AI Gateway (FastAPI)
- Integrate Claude, GPT, Kimi, Ollama
- Implement fallback, cost tracking, caching
- Build prompt registry
- Connect to BVR SDK

### Phase 4: Plugin System (Week 7-8)
- Define plugin manifest schema
- Build plugin loader
- Create GitHub, Slack, Azure plugins
- Implement health checks
- Build integration registry

### Phase 5: Workers & Workflows (Week 9-10)
- Build review worker (code analyzer)
- Build research worker (topic synthesizer)
- Build achieve worker (resume optimizer)
- Create Kestra orchestration workflows (HTTP-only)
- End-to-end testing

### Phase 6: Observability (Week 11-12)
- Instrument BVR SDK with OpenTelemetry
- Deploy Prometheus + Grafana + Loki + Jaeger
- Build BVR-specific dashboards
- Implement cost tracking per workflow
- Production hardening

---

## Business Outcomes (Measurable)

| Outcome | Metric | How Measured |
|---------|--------|--------------|
| Fix critical issues | < 20 min | Kestra SLA + BVR worker duration |
| Validated design | < 30 min | End-to-end workflow time |
| Decision-ready summary | < 10 min | BVR API response time |
| ATS score increase | +Y points | Pre/post comparison via worker |
| Cost reduction | X% monthly | AI Gateway cost attribution |
| Context switching | Reduced | Single BVR UI + API |
| Quality output | Higher | OPA verifier + Pydantic validation |
| Consistent standards | 100% | Policy enforcement on every event |

---

## Key Changes from v1

| Decision | v1 | v2 (This Revision) | Rationale |
|----------|-----|---------------------|-----------|
| Kestra role | Everything | Orchestration only | Business logic in your services |
| Business logic | Kestra tasks | BVR Workers | Separation of concerns |
| Event platform | Replaced | Preserved & enhanced | Your event-driven design is valuable |
| AI center | LangGraph | AI Gateway | LangGraph is a capability, not the center |
| Vector DB | Weaviate | PostgreSQL + pgvector | One DB, simpler ops |
| Message queue | Kafka | Redis Streams | Sufficient for current scale |
| Analytics | ClickHouse | PostgreSQL + Loki | Simpler, sufficient |
| API Gateway | Kong + Traefik | Traefik only | No overlap |
| SDK | Missing | BVR SDK | Standardized worker interface |
| Plugin system | Hard-coded | Manifest-based | Auto-discovery, extensibility |
| Platform registry | Missing | Central registry | Everything discoverable |
| AI Gateway | Missing | Unified gateway | Fallback, cost tracking, caching |
