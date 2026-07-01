import asyncio
import time

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="BVR Public Metrics", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bvrinfra.in",
        "https://www.bvrinfra.in",
        "http://localhost:5173",  # local dev
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SERVICES = {
    "api": "http://bvr-api:8000/health",
    "ai-gateway": "http://ai-gateway:8001/health",
    "kestra": "http://kestra:8081/health",
    "keycloak": "http://keycloak:8080/health/ready",
    "minio": "http://minio:9000/minio/health/live",
}

_cache: dict = {}
_cache_ts: float = 0.0
CACHE_TTL = 30


async def _ping(name: str, url: str, client: httpx.AsyncClient) -> tuple[str, bool]:
    try:
        r = await client.get(url, timeout=3.0)
        return name, r.status_code < 400
    except Exception:
        return name, False


async def _fetch() -> dict:
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_ping(n, u, client) for n, u in SERVICES.items()])

    statuses = {name: ok for name, ok in results}
    healthy = sum(statuses.values())
    total = len(statuses)

    if healthy == total:
        overall = "operational"
    elif healthy >= total // 2:
        overall = "degraded"
    else:
        overall = "down"

    uptime_pct = round((healthy / total) * 100, 1) if total else 0.0

    return {
        "platform_status": overall,
        "uptime_pct": uptime_pct,
        "services_healthy": healthy,
        "services_total": total,
        "services": statuses,
        "ai_providers": 4,       # Claude, GPT, Kimi, Ollama — from constitution.yaml
        "integrations": 3,        # claude, github, slack plugins
        "workers": 3,             # research, review, achieve
        "timestamp": int(time.time()),
    }


@app.get("/public")
async def public_metrics():
    global _cache, _cache_ts
    if time.time() - _cache_ts > CACHE_TTL:
        _cache = await _fetch()
        _cache_ts = time.time()
    return _cache


@app.get("/health")
async def health():
    return {"status": "ok", "service": "public-metrics"}
