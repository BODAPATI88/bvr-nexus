# CLAUDE.md — BVR Nexus

> **BVR Prime Directive: "If it doesn't reduce complexity, it doesn't belong."**

This file is the authoritative guide for working in this repository. Read it before touching any code.

---

## Platform Stability Policy (effective v2.0.0)

**The platform core is frozen.** v2.0.0 is General Availability. All future work falls into one of three tracks:

### Track 1 — Platform Maintenance (`release/v2.0.x`)
Bug fixes only. No new features, no new dependencies, no API changes.

**Allowed on `release/v2.0.x`:**
- Fixing confirmed bugs in existing behaviour
- Security patches
- Test additions that improve coverage of existing code
- Documentation corrections

**Not allowed on `release/v2.0.x`:**
- New endpoints, new service modules, new SDK functions
- New plugins, new workers, new Kestra workflows
- Dependency version bumps (unless security-driven)
- Refactors that change public interfaces

**Frozen files (do not modify except for bugs):**
- `api/main.py`, `api/services/`
- `workers/base.py`, `workers/research_worker.py`, `workers/review_worker.py`, `workers/achieve_worker.py`
- `bvr-sdk/bvr_sdk/`
- `ai-gateway/main.py`
- `governance/rego/`
- `contracts/constitution.yaml` (capabilities section)
- `api/init.sql`

### Track 2 — Product Integrations (`feature/integration-*`)
New business applications onboarded onto Nexus. Each integration is self-contained:
- New plugin in `plugins/<category>/<name>/` with full manifest
- New worker in `workers/`
- New Kestra workflow in `kestra-workflows/`
- New capability block in `contracts/constitution.yaml`
- No changes to frozen files

**First integration:** Pharmabridge (`feature/integration-pharmabridge`) — pending resume.

### Track 3 — Operations & Observability (`feature/ops-*`)
Operations Console, CEO Dashboard, Grafana dashboards, alerting rules, runbook automation.
These are additive — new services or new config files only.

### Release Versioning
| Version | Meaning |
|---------|---------|
| `v2.0.x` | Bug fix — no API or schema change |
| `v2.x.0` | New integration or ops feature — additive only |
| `v3.0.0` | Breaking change — requires migration guide |

---

## Table of Contents

1. [Repository Status](#repository-status)
2. [Architecture Overview](#architecture-overview)
3. [Layer Responsibilities](#layer-responsibilities)
4. [Data Flow](#data-flow)
5. [Technology Stack](#technology-stack)
6. [Engineering Principles](#engineering-principles)
7. [Git Workflow](#git-workflow)
8. [Deployment](#deployment)
9. [AI Implementation Rules](#ai-implementation-rules)
10. [Testing Requirements](#testing-requirements)
11. [Architecture Drift Prevention](#architecture-drift-prevention)

---

## Repository Status

This section is the authoritative distinction between what exists now and what is planned. Do not describe planned items as if they already exist.

### Implemented
- **BVR CLI** — `bvr-cli/main.py` (Typer + Rich); commands: `review`, `architect`, `research`, `achieve`, `status`, `workflows`, `workers`, `outcomes`, `models`, `plugins`
- **FastAPI Gateway** — `api/main.py`; auth (JWT + Keycloak), rate limiting, event routing, registry CRUD, approval system, Kestra webhooks
- **BVR Workers** — `workers/base.py`, `workers/research_worker.py`, `workers/review_worker.py`, `workers/achieve_worker.py`
- **BVR SDK** — `bvr-sdk/bvr_sdk/`; all platform operations (events, auth, storage, AI, telemetry, retry, policy, registry, plugin discovery, capability matching)
- **AI Gateway** — `ai-gateway/main.py`; capability-based LLM routing via `contracts/constitution.yaml`, Redis caching, cost tracking
- **Plugins** — `plugins/ai/claude`, `plugins/code/github`, `plugins/productivity/slack`; each has the full manifest structure
- **Contracts** — `contracts/constitution.yaml` (source of truth for capability→provider mapping); `contracts/` YAML schemas
- **Governance** — `governance/rego/bvr.rego`, `governance/rego/cost.rego`, `governance/rego/data_residency.rego`
- **Infrastructure** — PostgreSQL + pgvector, Redis, MinIO, Kestra, Traefik, OPA, Vault, Keycloak
- **Observability** — Prometheus, Grafana, Jaeger, Loki (config in `observability/`)
- **Kestra Workflows** — `kestra-workflows/achieve/resume-optimization.yml`, `kestra-workflows/research/topic.yml`, `kestra-workflows/review/repository.yml`

### Development-Only (must be remediated before production)
- `docker-compose.yml` contains multiple hardcoded credentials (`bvrsecret123`, `bvrsecret`, `bvr-root-token`, `bvradmin`). See [Deployment](#deployment) for details.
- Grafana admin password is hardcoded as `admin`/`admin` in `docker-compose.yml`.
- `VAULT_TOKEN: bvr-root-token` is a literal string in `docker-compose.yml`; Vault is running in server mode so this must be replaced with a properly initialized token.
- `make vault-setup` and `make keycloak-setup` Makefile targets are broken — they call `scripts/setup_vault.py` and `scripts/setup_keycloak.py` which do not exist. Run the shell scripts directly (see [Deployment](#deployment)).
- `make test` and `make test-integration` will fail — no `tests/` directory exists yet.

### Planned (not yet in repository)
- Web UI (FastAPI + Jinja2 / React SPA)
- VS Code Extension (TypeScript)
- Slack Bot (Bolt + FastAPI)
- Test suite (`tests/` directory, pytest + pytest-asyncio)
- `api/services/` service layer (database queries are currently inline in `api/main.py`)
- `observability/dashboards/` Grafana provisioning directory (referenced in `docker-compose.yml` but not present)
- OpenCost integration (cost tracking currently uses Redis counters in `ai-gateway/main.py`)

---

## Architecture Overview

BVR Nexus is a declarative workflow orchestration platform built on strict separation of concerns across seven layers (L0–L6):

```
Users (CLI / Web / VS Code / Slack)
    ↓
Traefik            — Ingress, TLS termination, routing
    ↓
FastAPI Gateway    — Auth, rate limiting, validation, event API
    ↓
┌──────────────────┬──────────────────┐
│                  │                  │
Kestra             BVR Event Bus      AI Gateway
(Orchestrate)      (Redis Streams)    (LLM Abstraction)
    │                  │                  │
    │          ┌───────┴───────┐          │
    │          │   Registry    │          │
    │          │  (Postgres)   │          │
    │          └───────┬───────┘          │
    │                  │                  │
    │          ┌───────┴───────┐          │
    │          │   Workers     │◄─────────┘
    │          │  (Python)     │
    │          └───────┬───────┘
    │                  │
    └──────────────────┘
                       │
               ┌───────┴───────┐
               │  MinIO        │
               │ (Artifacts)   │
               └───────────────┘
```

**The three invariants that must never change:**
1. Kestra orchestrates. It never runs business logic.
2. Workers execute. They only reach providers through the BVR SDK and AI Gateway.
3. The AI Gateway abstracts all LLM providers. No worker calls a provider API directly.

---

## Layer Responsibilities

### L0 — User Interface
| Component | Implementation | Status |
|-----------|---------------|--------|
| BVR CLI | `bvr-cli/main.py` (Typer + Rich) — calls FastAPI Gateway only | Implemented |
| Web UI | FastAPI + Jinja2 / React SPA | **Planned** |
| VS Code Extension | TypeScript | **Planned** |
| Slack Bot | Bolt + FastAPI | **Planned** |
| Ingress | Traefik only — TLS + routing (no Kong) | Implemented |

### L1 — Orchestration (Kestra)
Kestra workflows live in `kestra-workflows/`. They contain **only**:
- Webhook triggers
- HTTP calls to `POST /api/v1/events`
- Wait / pause / timeout conditions
- Retry and SLA enforcement
- Approval gates
- Slack/email notifications

Kestra workflows must **never** contain business logic, LLM calls, data transforms, or file I/O.

### L2 — Execution (BVR Event Platform)
| Component | Location | Responsibility |
|-----------|----------|---------------|
| FastAPI Gateway | `api/main.py` | Auth, rate limit, event validation, registry CRUD |
| Event Router | `api/` (Redis Streams) | Route events to correct worker consumer group |
| Platform Registry | PostgreSQL + `api/` | Workers, integrations, models, prompts — all discoverable |
| Workers | `workers/` | All business logic; inherit from `workers/base.py` |
| BVR SDK | `bvr-sdk/bvr_sdk/` | Standardized interface for every worker operation |

### L3 — Integration (Plugin System)
Every external integration is a plugin in `plugins/<category>/<name>/`:
- `manifest.yaml` — name, version, capabilities, dependencies
- `schema.yaml` — typed input/output contracts
- `permissions.yaml` — required secrets (via Vault)
- `health.py` — health check callable
- `worker.py` — execution logic

Implemented plugins: `plugins/ai/claude`, `plugins/code/github`, `plugins/productivity/slack`.

Plugins are auto-discovered at worker startup. Never hard-code integration logic outside a plugin.

### L4 — Data & State
| Store | Use | Why |
|-------|-----|-----|
| PostgreSQL + pgvector | Events, registry, knowledge base, audit log | One DB, one backup, one replication |
| Redis Streams | Event bus, consumer groups, cache | Sufficient at current scale; upgrade to Kafka only when Redis saturates |
| MinIO | Artifacts, reports | S3-compatible; do not use local filesystem for outputs |
| Loki | Raw log aggregation | Container deployed; `log_event()` currently writes to stdout. Log shipping to Loki is **Planned**. |

**Removed and must not return**: Weaviate, ClickHouse, Kafka, Kong, LangGraph as a center.

### L5 — Governance
| Component | Location | Role |
|-----------|----------|------|
| OPA | `governance/rego/` | Policy-as-code: RBAC, cost guardrails, data residency |
| Keycloak | External container | SSO, RBAC |
| Vault | External container | All secrets; never hardcoded |
| BVR SDK `policy.py` | `bvr-sdk/bvr_sdk/policy.py` | OPA client used by all workers |

Every event must pass an OPA policy check before a worker handles it. This happens in `BaseWorker._handle_event()`.

### L6 — Observability
All workers auto-instrument via BVR SDK decorators:
```python
from bvr_sdk import trace_span, log_metric

@trace_span("worker.task_name")
async def handle(self, event: EventEnvelope):
    await log_metric("worker.tasks", 1, {"type": event.event_type})
```

Stack: OpenTelemetry → Jaeger (traces) | Prometheus → Grafana (metrics) | Loki → Grafana (logs).

Cost tracking is implemented via Redis counters in `ai-gateway/main.py` (incremented per provider call). A dedicated cost observability tool (e.g., OpenCost) is **Planned** but not currently deployed.

---

## Data Flow

There are two entry paths into the system. Both converge at step 3.

**Path A — CLI (direct):** The CLI calls the FastAPI Gateway directly on port 8000. Kestra is not involved.

**Path B — Kestra-orchestrated:** An external system triggers a Kestra webhook. Kestra builds a DAG and calls the FastAPI Gateway.

```
[Path A] User intent → CLI → POST /api/v1/events (port 8000)
[Path B] External trigger → Kestra webhook → Kestra DAG → POST /api/v1/events

3. Gateway validates auth + rate limits
4. API validates EventEnvelope (Pydantic) → stores in PostgreSQL → publishes to Redis Stream
5. Workers read from Redis Stream (consumer group "bvr-workers")
6. Worker executes business logic using BVR SDK
7. Worker calls AI Gateway if LLM is needed
8. AI Gateway resolves provider via Capability Matcher → calls provider plugin
9. Provider fallback chain: Claude → GPT → Kimi → Ollama
10. Worker emits result event → Redis Stream
11. Gateway notifies Kestra via webhook callback (Path B only: /api/v1/webhooks/kestra)
12. Artifact uploaded → MinIO
13. Notification → Slack / email
```

---

## Technology Stack

| Layer | Tool | Version | Notes |
|-------|------|---------|-------|
| Orchestration | Kestra | v0.18.0 | Orchestration only |
| Ingress | Traefik | v3.1.0 | TLS + routing. No Kong. |
| Application API | FastAPI | 0.111.0 | Auth, events, registry |
| Event Bus | Redis Streams | 7.2.4 | Lightweight messaging |
| State / Vector | PostgreSQL + pgvector | pg16 | Primary data store |
| Cache | Redis | 7.2.4 | Cache + streams |
| Artifacts | MinIO | latest | S3-compatible |
| AI Gateway | FastAPI (custom) | — | `ai-gateway/main.py` |
| Workers | Python async (asyncio) | — | `workers/` |
| Policy | OPA | 0.65.0 | Pre/post execution |
| Auth | Keycloak | 25.0.1 | SSO, RBAC |
| Secrets | Vault | 1.17.0 | KV v2, production mode |
| Telemetry | OpenTelemetry | — | Auto-instrumented via SDK |
| Metrics | Prometheus | v2.53.0 | → Grafana |
| Logs | Loki | 3.0.0 | → Grafana |
| Traces | Jaeger | 1.58.0 | → Grafana |
| Local LLM | Ollama | 0.1.48 | llama3.3, last-resort fallback |

---

## Engineering Principles

### 1. Separation of Concerns (Non-Negotiable)
Each layer has one job. Mixing concerns across layers is the primary source of architecture drift.

- Kestra: schedule, retry, approve, notify — nothing else
- FastAPI Gateway: validate, authenticate, route — nothing else
- Workers: business logic only, always via BVR SDK
- AI Gateway: LLM abstraction only

### 2. Contracts as Constitution
`contracts/` and `contracts/constitution.yaml` define all capability-to-provider mappings. The Capability Matcher reads this at boot. Changes to provider priority belong here, not in worker code.

### 3. Everything Through the SDK
Workers must use `bvr_sdk` for all platform operations. Never import `httpx`, `boto3`, `anthropic`, `openai`, or provider SDKs directly inside a worker.

```python
# CORRECT
from bvr_sdk import ai_gateway_call, upload_artifact, emit_event

# WRONG — bypasses governance, cost tracking, fallback
import anthropic
client = anthropic.Anthropic()
```

### 4. Plugin-First for Integrations
New external integrations go in `plugins/<category>/<name>/` with a full manifest. They are never hard-coded in worker files.

### 5. Complexity Budget
Every dependency, abstraction, and new service must justify itself against the Prime Directive. When in doubt, use what is already in the stack.

### 6. Pydantic Everywhere
All event payloads, API request/response bodies, and plugin schemas use Pydantic models. No raw dicts crossing service boundaries.

### 7. Policy on Every Event
OPA governs every event before execution. Cost guardrails (`cost.rego`), RBAC (`bvr.rego`), and data residency (`data_residency.rego`) are enforced at the SDK layer — not ad-hoc inside workers.

---

## Git Workflow

### Branch Naming
```
feature/<short-description>      # New capability
fix/<short-description>          # Bug fix
refactor/<short-description>     # Code restructuring (no behavior change)
chore/<short-description>        # Deps, tooling, config
hotfix/<short-description>       # Emergency production fix
```

### Commit Style
One logical change per commit. Subject line: imperative mood, ≤ 72 characters.
```
add review worker with OPA policy check
fix ai-gateway fallback when Claude rate-limited
refactor base worker signal handling
```

### Pull Request Rules
- PRs target `main`; no direct pushes to `main`
- Every PR must pass: `make lint` + `make test`
- Security-touching changes (Vault, Keycloak, OPA, secrets) require an explicit audit comment in the PR body citing the relevant audit finding from `BVR_Nexus_v2_AUDIT_REPORT.md`
- `.env` must never appear in a commit; `.env.example` is the only allowed secrets template

### Protected Files
Never commit:
- `.env` (use `.env.example` as the template)
- Any file containing literal API keys, tokens, or passwords
- `docker-compose.yml` with hardcoded credentials (use `${VAR}` env substitution only — see current hardcoded credentials in the Deployment section below)

---

## Deployment

### Prerequisites
- Docker Engine 24.0+
- Docker Compose v2.20+
- 8 GB RAM minimum

### Start the Stack
```bash
# 1. Copy and populate environment
cp .env.example .env
make secrets          # auto-generates GENERATE placeholders

# 2. Add real API keys to .env
#    ANTHROPIC_API_KEY, OPENAI_API_KEY, KIMI_API_KEY, GITHUB_TOKEN, SLACK_WEBHOOK_URL

# 3. Start everything
make start            # runs ./start.sh → docker compose up

# 4. Initialize governance services (first run only)
#    NOTE: 'make vault-setup' and 'make keycloak-setup' are currently broken —
#    they call .py scripts that do not exist. Run the shell scripts directly:
bash scripts/setup_vault.sh
bash scripts/setup_keycloak.sh
```

### Hardcoded Development Credentials — Action Required Before Production

`docker-compose.yml` currently contains hardcoded development credentials that **must be replaced** before any production or shared deployment. These violate the "no hardcoded secrets" principle and are present for local development convenience only:

| Location | Credential | Action Required |
|----------|-----------|----------------|
| `bvr-api`, `bvr-workers` environment | `DATABASE_URL` with literal `bvrsecret` password | Replace with `${POSTGRES_PASSWORD}` |
| `minio-init` entrypoint | `bvradmin bvrsecret123` hardcoded | Replace with env vars |
| Kestra `KESTRA_CONFIGURATION` block | `accessKey: bvradmin` / `secretKey: bvrsecret123` | Replace with env vars |
| `bvr-api` environment | `VAULT_TOKEN: bvr-root-token` | Replace with Vault-issued token |
| `bvr-api`, `bvr-workers` environment | `MINIO_SECRET_KEY: bvrsecret123` | Replace with `${MINIO_ROOT_PASSWORD}` |
| Grafana environment | `GF_SECURITY_ADMIN_PASSWORD: admin` | Replace with `${GRAFANA_ADMIN_PASSWORD}` |
| Postgres, Keycloak | `:-changeme` default fallbacks | Remove fallbacks; require explicit vars |

Additionally, `.env.example` includes `VAULT_DEV_ROOT_TOKEN_ID` — this is a Vault dev-mode variable and has no effect when Vault runs in server mode (as configured in `scripts/vault.hcl`). The actual Vault token used by `bvr-api` is `VAULT_TOKEN` in `docker-compose.yml`, which must be replaced with a properly initialized server token after running `bash scripts/setup_vault.sh`.

### Service Ports
| Service | Port | URL |
|---------|------|-----|
| BVR API | 8000 | http://localhost:8000/docs |
| AI Gateway | 8001 | http://localhost:8001/v1/completions |
| Kestra UI | 8080 | http://localhost:8080 |
| Keycloak | 8081 | http://localhost:8081 |
| Traefik Dashboard | 8082 | http://localhost:8082 |
| Grafana | 3000 | http://localhost:3000 |
| MinIO Console | 9001 | http://localhost:9001 |
| Prometheus | 9090 | http://localhost:9090 |
| Jaeger | 16686 | http://localhost:16686 |
| Ollama | 11434 | http://localhost:11434 |

### Deployment-First Priority
Infrastructure changes are shipped before code that depends on them:
1. Schema changes (`api/init.sql`) deploy before API changes that require new columns
2. New plugin manifests deploy before workers that call them
3. OPA policy updates deploy before enforcement code changes
4. Never merge feature code that references unreleased infra

### Make Targets
```bash
make build            # Build all Docker images
make start            # Start full stack
make stop             # Stop all services (preserves data volumes)
make clean            # Stop + delete all volumes (destructive)
make logs             # Tail all logs
make logs-api         # Tail BVR API logs only
make logs-workers     # Tail worker logs only
make status           # Check system health via bvr-cli
make test             # Run pytest [BROKEN — no tests/ directory yet]
make test-integration # Run integration tests [BROKEN — no tests/ directory yet]
make lint             # ruff + black --check + mypy
make format           # ruff --fix + black (auto-format)
make security         # bandit + safety check
make backup           # pg_dump + MinIO snapshot
make secrets          # Generate GENERATE placeholders in .env
make vault-setup      # [BROKEN — calls setup_vault.py which does not exist; run bash scripts/setup_vault.sh]
make keycloak-setup   # [BROKEN — calls setup_keycloak.py which does not exist; run bash scripts/setup_keycloak.sh]
```

---

## AI Implementation Rules

### Rule 1: All LLM calls go through the AI Gateway
```python
# CORRECT — goes through fallback, cost tracking, caching
from bvr_sdk import ai_gateway_call

result = await ai_gateway_call(
    capability="code_analysis",
    prompt="...",
    model_preference="claude"   # hint only; Gateway may override
)

# WRONG — bypasses governance
import anthropic
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

### Rule 2: Provider priority is declared in `contracts/constitution.yaml`
Do not hard-code model names inside workers. Add a capability block to the constitution and let the Capability Matcher select the provider at runtime.

### Rule 3: Fallback chain
Claude (Anthropic) → GPT (OpenAI) → Kimi (Moonshot) → Ollama (local, free). The AI Gateway enforces this via the Capability Matcher reading `contracts/constitution.yaml`. Workers must not implement their own fallback logic.

### Rule 4: Per-workflow overrides belong in `constitution.yaml`
```yaml
workflow_overrides:
  bvr.achieve.resume-optimization:
    code_analysis:
      providers:
        - id: gpt_code
          priority: 1    # GPT preferred for resume writing
```

### Rule 5: Cost guardrails are enforced by OPA, not by workers
`governance/rego/cost.rego` enforces `max_cost_usd: 5.00` per execution and `$50/user/day`. Workers must not implement independent cost caps.

### Rule 6: Token tracking is handled server-side
Token usage is tracked by the AI Gateway service itself via Redis counters (incremented in `ai-gateway/main.py` per provider call). The SDK exposes a standalone `track_tokens()` function for manual use, but it is **not** called automatically by `ai_gateway_call()`. Workers must not implement their own independent token tracking.

### Rule 7: Prompts belong in the Prompt Registry
Prompts used by workers should be registered in the Platform Registry (`/api/v1/ai-gateway/prompts`), versioned, and retrieved by ID — not embedded as string literals in worker code. Inline prompts are acceptable only for truly one-off, non-reusable calls.

---

## Testing Requirements

### Current State
No `tests/` directory exists in this repository. The `make test` and `make test-integration` Makefile targets call `pytest tests/` but will fail immediately because the directory is absent. Writing the test suite is **Planned**.

### Planned Test Structure
When tests are added, follow this layout:

```
tests/
├── <module>/
│   └── test_<name>.py       # Unit tests
└── integration/
    └── test_<name>.py       # Integration tests (require running stack)
```

- Framework: `pytest` + `pytest-asyncio`
- Workers: test `handle()` in isolation by passing a mock `EventEnvelope`
- SDK calls: mock at the function level (`bvr_sdk.ai_gateway_call`, `bvr_sdk.emit_event`, etc.)
- OPA policy files: test with `opa test governance/rego/`

### Linting (required before every PR)
These targets work today:
```bash
make lint
# runs:
#   ruff check .       — fast linting
#   black --check .    — formatting check
#   mypy .             — type checking
```

### Security Scan (required for infra/auth/secrets changes)
```bash
make security
# runs:
#   bandit -r .        — Python security issues
#   safety check       — known vulnerable dependencies
```

### What Must Be Tested (once tests/ exists)
| Component | Required Coverage |
|-----------|-----------------|
| Every new worker `handle()` method | Unit test with mock event |
| Every new OPA policy | `opa test` with allow and deny cases |
| Every new plugin `worker.py` | Unit test with mocked external call |
| API endpoint changes | Pytest with `httpx.AsyncClient` |
| Schema / contract changes | Pydantic validation test |

### What Is Not Tested Here
- Kestra workflow YAML correctness (test in Kestra UI)
- Grafana dashboard JSON
- Docker Compose startup order (tested by `make start`)

---

## Architecture Drift Prevention

Drift happens when code migrates across layer boundaries without intention. These rules prevent it.

### Forbidden Patterns

| Pattern | Why Forbidden | Correct Alternative |
|---------|--------------|---------------------|
| Business logic in a Kestra YAML task | Violates L1/L2 boundary | Move to a Worker |
| Direct LLM provider import in a worker | Bypasses AI Gateway | Use `bvr_sdk.ai_gateway_call()` |
| Database query inline in `api/main.py` without a service module | Mixes routing and data access | Extract to a service module (Planned: `api/services/`) |
| Hardcoded secret in any file | Security audit C1 | Use `vault://secrets/...` reference + Vault |
| New vector store (Weaviate, Pinecone, etc.) | Already solved by pgvector | Extend `api/init.sql` |
| New message queue (Kafka, RabbitMQ) | Already solved by Redis Streams | Add consumer group to existing streams |
| New API gateway (Kong, NGINX) | Already solved by Traefik | Add Traefik middleware/router |
| Worker importing another worker directly | Creates hidden coupling | Emit an event; let the Router dispatch |
| Plugin logic outside `plugins/<category>/<name>/` | Breaks auto-discovery | Create proper plugin with manifest |
| Secrets in `.env` committed to git | Security critical | Use `.env.example` only |

### Layer Boundary Checklist (for every PR)
Before submitting a PR, confirm:
- [ ] Kestra YAML contains only HTTP tasks, waits, and notifications
- [ ] Workers only import from `bvr_sdk`, `workers.base`, and stdlib/typing
- [ ] All LLM calls use `ai_gateway_call()` from the SDK
- [ ] All secrets reference `vault://secrets/...` or env vars from `.env`
- [ ] New integrations have a full plugin manifest in `plugins/`
- [ ] New capabilities are declared in `contracts/constitution.yaml`
- [ ] `make lint` passes
- [ ] `make test` passes (once tests/ directory exists)

### Canonical Directory Map
```
bvr-nexus/
├── ai-gateway/         # AI Gateway service — LLM abstraction only
├── api/                # FastAPI Gateway — auth, events, registry CRUD
│   └── init.sql        # DB schema — migrate here, nowhere else
├── bvr-cli/            # CLI entry point — calls API only
├── bvr-sdk/            # SDK — the ONLY way workers talk to infrastructure
│   └── bvr_sdk/
├── contracts/          # YAML Constitution — capability-to-provider mapping
├── gateway/            # Traefik config only
├── governance/         # OPA rego policies only
├── kestra-workflows/   # Orchestration YAML only — NO business logic
├── observability/      # Prometheus, Loki config (Grafana dashboards: Planned)
├── plugins/            # One directory per integration, with full manifest
├── scripts/            # One-time setup scripts (setup_vault.sh, setup_keycloak.sh)
├── tests/              # [Planned] pytest unit and integration tests
└── workers/            # Business logic only, always via BVR SDK
```

### Adding a New Capability — Required Steps
1. Add capability block to `contracts/constitution.yaml` with provider priority list
2. Create plugin in `plugins/<category>/<name>/` with manifest, schema, permissions, health, worker
3. Write worker in `workers/` extending `BaseWorker`
4. Write unit tests in `tests/` (once tests/ directory exists)
5. Register worker in Platform Registry (automatic via `register_worker()` in `BaseWorker.start()`)
6. Add Kestra workflow YAML in `kestra-workflows/` that calls the API — nothing more

### Adding a New LLM Provider — Required Steps
1. Add provider config to AI Gateway (`ai-gateway/main.py`)
2. Add provider block to `contracts/constitution.yaml` under relevant capabilities
3. Add API key placeholder to `.env.example`
4. Update `governance/rego/cost.rego` if the provider has different cost characteristics
5. No changes needed in any worker

---

## Key Reference Documents

| Document | Purpose |
|----------|---------|
| `BVR_Nexus_Revised_Architecture_v2.md` | Full architecture specification |
| `BVR_Nexus_v2_AUDIT_REPORT.md` | Security findings — track resolution here |
| `BVR_Nexus_v2_AUDIT_SUMMARY.md` | Audit summary with remediation priority |
| `contracts/constitution.yaml` | Capability-to-provider mapping (source of truth) |
| `contracts/` | All YAML contract schemas |
| `.env.example` | Environment template — never `.env` |
