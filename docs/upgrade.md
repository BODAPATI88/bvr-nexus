# BVR Nexus — Upgrade Guide

---

## v2.0.0 — Initial Release

BVR Nexus v2.0.0 is the first General Availability release. There is no prior version to upgrade from.

---

## Upgrading to Future v2.x Releases

This section describes the upgrade procedure for future patch and minor releases within the v2.x line.

### Before upgrading

1. **Read the release notes** for the target version. Each release notes file documents breaking changes, schema migrations, and config changes.
2. **Back up PostgreSQL** and MinIO before applying any upgrade:
   ```bash
   make backup
   ```
3. **Pin your current version** in a rollback branch:
   ```bash
   git tag v<current-version>-pre-upgrade
   ```

### Standard upgrade procedure

```bash
# 1. Pull the new version
git fetch origin
git checkout v<target-version>

# 2. Apply schema migrations (if any)
#    Check the release notes for SQL migration files.
#    All schema changes are idempotent — re-running init.sql is safe.
docker compose exec bvr-api cat /app/init.sql | docker compose exec -T postgres psql -U bvr bvr

# 3. Rebuild and restart services
make build
make stop
make start

# 4. Verify health
make status
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### Plugin upgrades

If a plugin's `manifest.yaml` changes, the SHA256 verification in `workers/base.py` and `bvr-sdk/bvr_sdk/plugin_registry.py` will detect the change and log the new hash. No manual action is required unless `manifest_sha256` is set to an expected value in the manifest itself.

---

## Schema Migration Policy

All schema changes must be:

1. **Additive and idempotent** — use `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
2. **Applied before rolling the API** — never deploy code that requires a new column before the column exists
3. **Declared in `api/init.sql`** — this file is the authoritative schema definition

Destructive schema changes (dropping columns, renaming tables) require a multi-step migration:
1. Release 1: keep old column, add new column, code handles both
2. Release 2: migrate data, switch code to new column only
3. Release 3: drop old column

---

## Breaking Change Policy

BVR Nexus follows semantic versioning:

| Version bump | Meaning |
|--------------|---------|
| Patch (2.0.x) | Bug fixes only; no API or schema changes |
| Minor (2.x.0) | New features; API additions only (no removals) |
| Major (3.0.0) | May include breaking API changes, schema restructuring |

### What counts as a breaking change

- Removing or renaming a field in the `EventEnvelope` schema
- Removing an API endpoint
- Changing authentication mechanisms
- Removing a capability from `contracts/constitution.yaml`
- Changing the Redis stream name (`bvr-events`) or consumer group name (`bvr-workers`)

### What does not count as a breaking change

- Adding optional fields to request/response bodies
- Adding new API endpoints
- Adding new capabilities to the constitution
- Adding new plugins
- Changing provider priority order in the constitution

---

## Kubernetes Upgrade

For Kubernetes deployments, apply manifests with `kubectl apply -f k8s/` after pulling the new version. For rolling updates with zero downtime:

```bash
# Apply any new or changed manifests
kubectl apply -f k8s/

# Roll deployments to pick up new image tags
kubectl rollout restart deployment/bvr-api -n bvr-nexus
kubectl rollout restart deployment/bvr-workers -n bvr-nexus
kubectl rollout restart deployment/ai-gateway -n bvr-nexus

# Monitor rollout
kubectl rollout status deployment/bvr-api -n bvr-nexus
kubectl rollout status deployment/bvr-workers -n bvr-nexus
```

---

## Rollback

If an upgrade causes failures:

```bash
# Docker Compose rollback
git checkout v<previous-version>
make build
make stop
make start
```

For Kubernetes:
```bash
kubectl rollout undo deployment/bvr-api -n bvr-nexus
kubectl rollout undo deployment/bvr-workers -n bvr-nexus
```

Database rollback requires restoring from the backup taken before the upgrade. Schema rollbacks (dropping added columns) must be done manually with `ALTER TABLE ... DROP COLUMN`.
