# BVR Nexus — Known Limitations

This document lists limitations in the current v2.0.0 release. Each item includes its category and the planned remediation path.

---

## L0 — User Interface

### Web UI not built
**Status:** Planned  
The `docs/architecture.md` and CLAUDE.md reference a Web UI (FastAPI + React SPA or Jinja2). No implementation exists yet. The FastAPI Gateway is fully functional and exposes a Swagger UI at `http://localhost:8000/docs` which can be used as an interim interface.

### VS Code Extension not built
**Status:** Planned  
A TypeScript VS Code extension is listed as a planned L0 interface. Not yet implemented.

### Slack Bot not built
**Status:** Planned  
A Bolt + FastAPI Slack bot is listed as a planned L0 interface. Not yet implemented. Slack *notifications* (outbound webhooks) work via the Slack plugin at `plugins/productivity/slack/`.

---

## L4 — Data & State

### Log shipping requires a log driver
**Status:** Requires operator action  
Loki is deployed and configured with the TSDB storage backend (`observability/loki-config.yml`). However, container logs are only available in Loki if a log shipping agent (e.g., Promtail, Grafana Alloy, or a Docker logging driver) is configured to forward them. Without a log driver, `log_event()` in the BVR SDK writes to stdout only and does not appear in Grafana Loki.

To enable: configure the Docker logging driver in `docker-compose.yml` or deploy Promtail as a DaemonSet in Kubernetes.

### Grafana dashboards directory not provisioned
**Status:** Planned  
`docker-compose.yml` references `./observability/dashboards/` as a Grafana provisioning volume, but this directory does not exist in the repository. Grafana starts successfully but without any pre-loaded dashboards. Dashboards must be created manually via the Grafana UI or imported from JSON.

---

## L5 — Governance

### Vault unseal keys must be stored externally
**Status:** Requires operator action  
Vault runs in server mode (not dev mode). After running `bash scripts/setup_vault.sh`, Vault prints unseal keys and a root token. These are displayed once and not stored anywhere by the script. The operator must:
1. Store the unseal keys in an external secret store (password manager, HSM, etc.)
2. Unseal Vault after every container restart using at least 3 of the 5 keys

### Docker Compose has hardcoded development credentials
**Status:** Known issue — production remediation required  
Several values in `docker-compose.yml` are hardcoded for local development convenience (`bvrsecret123`, `bvradmin`, `bvr-root-token`). These must be replaced with `${ENV_VAR}` references before any production or shared deployment. See the full list in `docs/deployment.md` and the audit findings in `BVR_Nexus_v2_AUDIT_REPORT.md`.

---

## Makefile

### `make vault-setup` and `make keycloak-setup` are broken
**Status:** Known issue  
These Makefile targets call `scripts/setup_vault.py` and `scripts/setup_keycloak.py` which do not exist in the repository. Use the shell scripts directly:
```bash
bash scripts/setup_vault.sh
bash scripts/setup_keycloak.sh
```

---

## Cost Observability

### OpenCost not deployed
**Status:** Planned  
Cost tracking is currently implemented via Redis counters in `ai-gateway/main.py` (incremented per provider call). The counters are exposed via `/metrics` and scraped by Prometheus. A dedicated cost observability tool (e.g., OpenCost) is planned but not currently deployed.

### `.env.example` contains `VAULT_DEV_ROOT_TOKEN_ID`
**Status:** Known mismatch  
`VAULT_DEV_ROOT_TOKEN_ID` is a Vault dev-mode variable and has no effect when Vault runs in server mode (as configured in `scripts/vault.hcl`). The actual token used by `bvr-api` is `VAULT_TOKEN`. The `VAULT_DEV_ROOT_TOKEN_ID` entry in `.env.example` is a harmless leftover from early development and can be ignored.

---

## Testing

### No integration tests
**Status:** Planned  
The `tests/` directory contains unit tests only. Integration tests that verify the full event flow (CLI → API → Redis → Worker → Result) require a running stack and are not yet implemented. The `make test-integration` target exists in the Makefile but has no test files to run.
