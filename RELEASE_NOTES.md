# BVR Nexus v2.0.0 — Release Notes

**Release date:** 2026-07-01
**Status:** General Availability

---

## Overview

BVR Nexus v2.0.0 is the first production-ready release of the declarative workflow orchestration platform. It provides event-driven AI workflow execution across a seven-layer architecture, with a tested plugin framework, Kubernetes deployment manifests, and full observability.

---

## Platform Components

| Component | Technology | Version |
|-----------|-----------|---------|
| BVR CLI | Python / Typer + Rich | 2.0.0 |
| API Gateway | FastAPI | 0.111.0 |
| AI Gateway | FastAPI (custom) | 2.0.0 |
| BVR Workers | Python asyncio | 2.0.0 |
| BVR SDK | Python | 2.0.0 |
| Event Bus | Redis Streams | 7.2.4 |
| Database | PostgreSQL + pgvector | pg16 |
| Orchestration | Kestra | v0.18.0 |
| Ingress | Traefik | v3.1.0 |
| Secrets | HashiCorp Vault | 1.17.0 |
| Identity | Keycloak | 25.0.1 |
| Policy | OPA | 0.65.0 |
| Artifacts | MinIO | RELEASE.2024-08-03 |
| Metrics | Prometheus + Grafana | v2.53.0 / 11.0.0 |
| Traces | Jaeger | 1.58.0 |
| Logs | Loki | 3.0.0 |

---

## Bundled Plugins

| Plugin | Category | Capabilities |
|--------|----------|--------------|
| Claude (Anthropic) | AI | code_analysis, content_generation, research |
| GPT (OpenAI) | AI | code_analysis, content_generation, research |
| Kimi (Moonshot) | AI | code_analysis, content_generation, research |
| Echo | AI | testing, development |
| GitHub | Code | repository_access, pull_requests, issues |
| Slack | Productivity | notifications, messaging |

---

## AI Gateway

- **Provider fallback chain:** Claude → GPT → Kimi → Ollama
- **Capability-based routing** via `contracts/constitution.yaml`
- **Circuit breaker** per provider (threshold: 5 failures, recovery: 60s)
- **Redis caching** for identical prompts
- **SSE streaming** (`GET /v1/stream`) for real-time token delivery
- **Cost tracking** via Redis counters per provider call
- **Per-workflow overrides** in `constitution.yaml`

---

## Kestra Workflows

Three production workflows included:

| Workflow | Trigger | Description |
|----------|---------|-------------|
| `bvr.review.repository` | Webhook | Architecture and code review |
| `bvr.research.topic` | Webhook | Topic research and synthesis |
| `bvr.achieve.resume-optimization` | Webhook | Resume optimization pipeline |

All workflows use webhook callback (`/api/v1/webhooks/kestra/wait/{id}`) for async completion — no fixed polling delays.

---

## Security Hardening

All eight critical and ten high audit findings addressed:

- All credentials use `${VAR}` env substitution — no hardcoded secrets
- Vault runs in server mode with file backend
- Kestra basic auth enabled
- Traefik TLS on `:443` with HTTP→HTTPS redirect
- Redis requires password authentication
- OPA not port-exposed (internal network only)
- Docker socket not mounted into Kestra
- JWT authentication on all BVR API endpoints
- Rate limiting: 100 req/min per client key
- Payload size limits and content-type enforcement
- MinIO SSE-S3 encryption at rest
- Resource limits on all containers
- Plugin manifest SHA256 verification before execution
- Dead letter queue for failed events

---

## Kubernetes

Complete manifest set for cluster deployment:

```
k8s/
├── 00-namespace.yaml        PostgreSQL
├── 01-configmap.yaml        Redis
├── 02-pvcs.yaml             MinIO
├── 03-postgres.yaml         OPA
├── 03b-db-migrate.yaml      Vault
├── 04-redis.yaml            Kestra
├── 05-minio.yaml            Keycloak
├── 06-opa.yaml              Jaeger
├── 07-vault.yaml            BVR API
├── 08-kestra.yaml           AI Gateway
├── 08b-keycloak.yaml        Workers
├── 09-jaeger.yaml           Traefik
├── 10-bvr-api.yaml          Prometheus
├── 11-ai-gateway.yaml       Grafana
├── 12-bvr-workers.yaml      Loki
├── 13-ingressroute.yaml     Redis Exporter
├── 14-prometheus.yaml
├── 15-grafana.yaml
├── 16-loki.yaml
├── 17-traefik.yaml
├── 18-redis-exporter.yaml
└── create-secrets.sh
```

---

## Test Coverage

**195 automated tests** across five test suites:

| Suite | Tests | Scope |
|-------|-------|-------|
| `tests/test_config.py` | 7 | Config hygiene, .gitignore, env coverage |
| `tests/test_plugin_manifests.py` | ~20 | Plugin manifest structure validation |
| `tests/api/` | ~80 | API endpoints, service layer, middleware |
| `tests/ai_gateway/` | ~30 | Circuit breaker, SSE streaming |
| `tests/workers/` | ~58 | Base worker, research, review, achieve workers |

---

## Known Limitations

See [docs/known-limitations.md](docs/known-limitations.md) for the full list. Key items:

- Web UI, VS Code Extension, and Slack Bot are planned but not built
- Log shipping from containers to Loki requires a log driver (e.g., Promtail)
- Vault unseal keys must be stored externally after `bash scripts/setup_vault.sh`
- `make vault-setup` and `make keycloak-setup` targets call shell scripts, not Python

---

## Upgrade Guide

This is the initial GA release. For future upgrades see [docs/upgrade.md](docs/upgrade.md).

---

## Documentation

| Document | Path |
|----------|------|
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Deployment Guide | [docs/deployment.md](docs/deployment.md) |
| Operations Runbook | [docs/runbook.md](docs/runbook.md) |
| Plugin Development | [docs/plugin-development.md](docs/plugin-development.md) |
| API Reference | [docs/api.md](docs/api.md) |
| Known Limitations | [docs/known-limitations.md](docs/known-limitations.md) |
| Upgrade Guide | [docs/upgrade.md](docs/upgrade.md) |
