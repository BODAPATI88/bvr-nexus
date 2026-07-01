"""
BVR Nexus Operations Console
Aggregates live data from the BVR API and AI Gateway for two audiences:
  GET /          → Operations Console (platform engineering)
  GET /ceo       → Executive Dashboard (business leadership)
  GET /health    → Health check
"""
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="BVR Ops Console", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

BVR_API = os.getenv("BVR_API_URL", "http://bvr-api:8000")
AI_GW = os.getenv("AI_GATEWAY_URL", "http://ai-gateway:8001")
PROM = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
TOKEN = os.getenv("BVR_SERVICE_TOKEN", "")
VERSION = "2.0.0"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

async def _get(url: str, token: str = "") -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(url, headers=headers)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def _prom_query(metric: str) -> float | None:
    """Run an instant PromQL query, return scalar result."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{PROM}/api/v1/query", params={"query": metric})
            if r.status_code == 200:
                result = r.json().get("data", {}).get("result", [])
                if result:
                    return float(result[0]["value"][1])
    except Exception:
        pass
    return None


def _status_class(status: str | None) -> str:
    if not status:
        return "status-unknown"
    s = status.lower()
    if s in ("ok", "healthy", "active", "up", "closed"):
        return "status-ok"
    if s in ("degraded", "half-open", "warn", "warning"):
        return "status-warn"
    return "status-err"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Operations Console  (engineering / on-call view)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def operations(request: Request):
    api_health = await _get(f"{BVR_API}/health")
    gw_health = await _get(f"{AI_GW}/health")

    workers = await _get(f"{BVR_API}/api/v1/registry/workers", TOKEN) or []
    integrations = await _get(f"{BVR_API}/api/v1/registry/integrations", TOKEN) or []
    capabilities_raw = await _get(f"{AI_GW}/v1/capabilities") or []

    # Normalise capabilities — API may return list of strings or list of dicts
    capabilities = []
    if isinstance(capabilities_raw, list):
        for item in capabilities_raw:
            if isinstance(item, str):
                capabilities.append({"id": item, "name": item})
            elif isinstance(item, dict):
                capabilities.append(item)

    # Fetch provider circuit-breaker state per capability
    provider_states: dict[str, list] = {}
    for cap in capabilities:
        cap_id = cap.get("id") or cap.get("name", "")
        providers = await _get(f"{AI_GW}/v1/providers/{cap_id}")
        if providers and isinstance(providers, list):
            provider_states[cap_id] = providers

    # Prometheus quick-checks
    api_up = await _prom_query('up{job="bvr-api"}')
    gw_up = await _prom_query('up{job="ai-gateway"}')
    redis_up = await _prom_query('up{job="redis-exporter"}')

    services = [
        {"name": "BVR API", "url": f"{BVR_API}/health",
         "status": (api_health or {}).get("status", "down"),
         "prom_up": api_up},
        {"name": "AI Gateway", "url": f"{AI_GW}/health",
         "status": (gw_health or {}).get("status", "down"),
         "prom_up": gw_up},
        {"name": "Redis", "url": None,
         "status": "up" if redis_up == 1.0 else ("down" if redis_up == 0.0 else "unknown"),
         "prom_up": redis_up},
    ]

    return templates.TemplateResponse(request, "operations.html", {
        "page": "ops",
        "version": VERSION,
        "refreshed": _now_utc(),
        "services": services,
        "workers": workers if isinstance(workers, list) else [],
        "integrations": integrations if isinstance(integrations, list) else [],
        "capabilities": capabilities,
        "provider_states": provider_states,
        "status_class": _status_class,
    })


# ---------------------------------------------------------------------------
# Executive / CEO Dashboard
# ---------------------------------------------------------------------------

@app.get("/ceo", response_class=HTMLResponse)
async def ceo_dashboard(request: Request):
    outcomes = await _get(f"{BVR_API}/api/v1/outcomes", TOKEN) or []
    models = await _get(f"{BVR_API}/api/v1/ai-gateway/models", TOKEN) or []
    integrations = await _get(f"{BVR_API}/api/v1/registry/integrations", TOKEN) or []
    workers = await _get(f"{BVR_API}/api/v1/registry/workers", TOKEN) or []

    api_health = await _get(f"{BVR_API}/health")
    gw_health = await _get(f"{AI_GW}/health")

    # Prometheus-derived KPIs
    total_events = await _prom_query('sum(http_requests_total{job="bvr-api", path="/api/v1/events"})')
    # Fallback: count outcomes as a proxy for completed workflows
    if total_events is None:
        total_events = len(outcomes) if isinstance(outcomes, list) else 0

    platform_ok = (
        (api_health or {}).get("status") == "ok"
        and (gw_health or {}).get("status") == "ok"
    )

    active_workers = len(workers) if isinstance(workers, list) else 0
    active_integrations = len(integrations) if isinstance(integrations, list) else 0
    active_models = len(models) if isinstance(models, list) else 0

    return templates.TemplateResponse(request, "ceo.html", {
        "page": "ceo",
        "version": VERSION,
        "refreshed": _now_utc(),
        "platform_ok": platform_ok,
        "total_events": int(total_events) if total_events else "—",
        "active_workers": active_workers,
        "active_integrations": active_integrations,
        "active_models": active_models,
        "outcomes": outcomes if isinstance(outcomes, list) else [],
        "models": models if isinstance(models, list) else [],
        "integrations": integrations if isinstance(integrations, list) else [],
        "status_class": _status_class,
    })


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ops-console", "version": VERSION}
