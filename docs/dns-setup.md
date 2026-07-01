# DNS Setup — bvrinfra.in

This document lists every DNS record required to fully expose BVR Nexus at `bvrinfra.in`.

All records are `A` records pointing to the MetalLB external IP assigned to the Traefik `LoadBalancer` Service.

## Find the Traefik External IP

```bash
kubectl get svc traefik -n bvr-nexus
# NAME      TYPE           CLUSTER-IP     EXTERNAL-IP    PORT(S)
# traefik   LoadBalancer   10.43.12.55    <EXTERNAL-IP>  80/TCP,443/TCP
```

Replace `<EXTERNAL-IP>` in every record below with the value from `EXTERNAL-IP`.

## DNS Records

| Subdomain | Type | Value | Service |
|-----------|------|-------|---------|
| `bvrinfra.in` | A | `<EXTERNAL-IP>` | Public website |
| `www.bvrinfra.in` | A | `<EXTERNAL-IP>` | Public website (alias) |
| `api.bvrinfra.in` | A | `<EXTERNAL-IP>` | BVR API Gateway |
| `ai.bvrinfra.in` | A | `<EXTERNAL-IP>` | AI Gateway |
| `ops.bvrinfra.in` | A | `<EXTERNAL-IP>` | Operations Console |
| `ceo.bvrinfra.in` | A | `<EXTERNAL-IP>` | Executive Dashboard |
| `grafana.bvrinfra.in` | A | `<EXTERNAL-IP>` | Grafana |
| `prometheus.bvrinfra.in` | A | `<EXTERNAL-IP>` | Prometheus |
| `jaeger.bvrinfra.in` | A | `<EXTERNAL-IP>` | Jaeger (traces) |
| `loki.bvrinfra.in` | A | `<EXTERNAL-IP>` | Loki (logs) |
| `keycloak.bvrinfra.in` | A | `<EXTERNAL-IP>` | Keycloak (SSO) |
| `vault.bvrinfra.in` | A | `<EXTERNAL-IP>` | Vault (secrets) — internal only |
| `kestra.bvrinfra.in` | A | `<EXTERNAL-IP>` | Kestra (orchestration) |
| `minio.bvrinfra.in` | A | `<EXTERNAL-IP>` | MinIO console |
| `argo.bvrinfra.in` | A | `<EXTERNAL-IP>` | ArgoCD |

## Ingress Files

| File | Namespace | Hosts covered |
|------|-----------|---------------|
| `k8s/ingress-public.yaml` | `bvr-nexus` | `bvrinfra.in`, `www.bvrinfra.in` |
| `k8s/ingress-api.yaml` | `bvr-nexus` | `api.bvrinfra.in`, `ai.bvrinfra.in` |
| `k8s/ingress-ops.yaml` | `bvr-nexus` | `ops.bvrinfra.in`, `ceo.bvrinfra.in` |
| `k8s/ingress-monitoring.yaml` | `bvr-nexus` | `grafana`, `prometheus`, `jaeger`, `loki` |
| `k8s/ingress-security.yaml` | `bvr-nexus` | `keycloak`, `vault`, `kestra` |
| `k8s/ingress-admin.yaml` | `bvr-nexus` | `minio.bvrinfra.in` |
| `k8s/ingress-argocd.yaml` | `argocd` | `argo.bvrinfra.in` |

## TLS — Let's Encrypt ACME

Traefik handles TLS certificate issuance and renewal automatically via the `le` cert resolver (HTTP-01 challenge). Certificates are stored in a `PersistentVolumeClaim` (`traefik-acme`, 128 Mi) at `/acme/acme.json` inside the Traefik container.

**Prerequisites for ACME to succeed:**
1. All DNS records above must resolve to the Traefik external IP before Traefik starts issuing certificates.
2. Port 80 must be publicly reachable from the internet (Let's Encrypt validation).
3. `ACME_EMAIL` must be set in the K8s Secret (populated via `bash k8s/create-secrets.sh`).

**Verify certificate issuance:**
```bash
# Watch Traefik logs for ACME activity
kubectl logs -n bvr-nexus -l app=traefik -f | grep -i acme

# Check acme.json content (after certs are issued)
kubectl exec -n bvr-nexus deploy/traefik -- cat /acme/acme.json | python3 -m json.tool | grep -A3 '"domain"'
```

## Security Notes

- **`vault.bvrinfra.in`** — Vault should be restricted to internal/VPN access only. Apply a Traefik `IPAllowList` middleware to `k8s/ingress-security.yaml` before exposing publicly:
  ```yaml
  # Add to ingress-security.yaml annotations:
  traefik.ingress.kubernetes.io/router.middlewares: bvr-nexus-vault-ip-allowlist@kubernetescrd
  ```
  Then create a `Middleware` CRD with your VPN CIDR.

- **`prometheus.bvrinfra.in`** and **`loki.bvrinfra.in`** — Prometheus and Loki do not have built-in authentication. Consider protecting them with Traefik's `BasicAuth` middleware if they are externally accessible.

- **`minio.bvrinfra.in`** — Protected by MinIO's own authentication. Ensure a strong admin password is set in Vault before exposing publicly.

## Applying Ingresses

ArgoCD tracks `k8s/` on `main` and syncs automatically. To apply manually:

```bash
# Platform ingresses (bvr-nexus namespace)
kubectl apply -f k8s/ingress-public.yaml
kubectl apply -f k8s/ingress-api.yaml
kubectl apply -f k8s/ingress-ops.yaml
kubectl apply -f k8s/ingress-monitoring.yaml
kubectl apply -f k8s/ingress-security.yaml
kubectl apply -f k8s/ingress-admin.yaml

# ArgoCD ingress (argocd namespace — apply separately)
kubectl apply -f k8s/ingress-argocd.yaml
```

## Port Reference (for local docker-compose development)

| Service | Local URL |
|---------|-----------|
| BVR API | http://localhost:8000/docs |
| AI Gateway | http://localhost:8001/v1/completions |
| Ops Console | http://localhost:8002 |
| Public Site | http://localhost:8003 |
| Kestra UI | http://localhost:8080 |
| Keycloak | http://localhost:8081 |
| Traefik Dashboard | http://localhost:8082 |
| Grafana | http://localhost:3000 |
| MinIO Console | http://localhost:9001 |
| Prometheus | http://localhost:9090 |
| Jaeger | http://localhost:16686 |
