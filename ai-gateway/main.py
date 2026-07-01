"""
BVR AI Gateway v2.1 — Uses Capability Matcher for provider selection.
Reads the Constitution for declared priorities, not hardcoded fallbacks.
"""

import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Add bvr-sdk to path
sys.path.insert(0, "/app/bvr-sdk")
from bvr_sdk import CapabilityNotFound, NoHealthyProvider, get_matcher

app = FastAPI(title="BVR AI Gateway", version="2.1.0")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_CB_FAILURE_THRESHOLD = int(os.getenv("BVR_CB_FAILURE_THRESHOLD", "5"))
_CB_RECOVERY_TIMEOUT = int(os.getenv("BVR_CB_RECOVERY_TIMEOUT", "60"))


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Per-provider circuit breaker with half-open recovery.

    States:
      closed   — normal operation
      open     — all calls rejected until recovery_timeout elapses
      half-open — one probe call allowed; success → closed, failure → open
    """

    def __init__(self, failure_threshold: int, recovery_timeout: int):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._state = "closed"

    def is_open(self) -> bool:
        """Return True when the provider should be skipped."""
        if self._state == "open":
            if time.time() - self._opened_at >= self.recovery_timeout:
                self._state = "half-open"
                return False  # allow one probe
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = time.time()


_circuit_breakers: Dict[str, CircuitBreaker] = {}


def _get_cb(provider_id: str) -> CircuitBreaker:
    if provider_id not in _circuit_breakers:
        _circuit_breakers[provider_id] = CircuitBreaker(
            _CB_FAILURE_THRESHOLD, _CB_RECOVERY_TIMEOUT
        )
    return _circuit_breakers[provider_id]


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

async def get_redis():
    return await redis.from_url(REDIS_URL, decode_responses=True)


def get_cache_key(req: dict) -> str:
    key_data = (
        f"{req.get('capability')}:{req.get('prompt')}:"
        f"{req.get('model_preference')}:{req.get('max_tokens')}:{req.get('temperature')}"
    )
    return hashlib.sha256(key_data.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CompletionRequest(BaseModel):
    capability: str = Field(
        ..., description="Required capability: code, reasoning, analysis, creative, summarization"
    )
    prompt: str = Field(..., description="The prompt text")
    model_preference: Optional[str] = Field(
        None, description="Preferred provider ID from Constitution"
    )
    max_tokens: int = Field(4000, ge=1, le=32000)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    use_cache: bool = Field(True, description="Whether to use response caching")
    stream: bool = Field(False, description="Whether to stream response")
    workflow_id: Optional[str] = Field(
        None, description="Optional workflow ID for per-workflow overrides"
    )


class CompletionResponse(BaseModel):
    text: str
    model_used: str
    provider: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    cached: bool = False
    duration_ms: Optional[int] = None


# ---------------------------------------------------------------------------
# Provider call
# ---------------------------------------------------------------------------

async def call_provider(
    plugin_id: str, config: dict, prompt: str, max_tokens: int, temperature: float
) -> Dict[str, Any]:
    from bvr_sdk import get_registry

    registry = get_registry()
    plugin = registry.get_plugin(plugin_id)

    if not plugin or not plugin.get("worker_module"):
        raise ValueError(f"Provider plugin not found: {plugin_id}")

    execute_func = getattr(plugin["worker_module"], "execute")
    return await execute_func(
        config,
        {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system_prompt": "",
        },
    )


# ---------------------------------------------------------------------------
# Completions endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/completions", response_model=CompletionResponse)
async def completions(request: CompletionRequest):
    """
    Main completion endpoint using Capability Matcher for provider selection.

    The Capability Matcher reads the Constitution at boot and knows:
    - Which providers implement each capability
    - Their priority order, health status, and cost models

    Circuit breakers prevent repeated calls to failing providers and allow
    automatic recovery after *BVR_CB_RECOVERY_TIMEOUT* seconds.
    """
    start_time = time.time()

    # Cache read
    if request.use_cache:
        cache_key = get_cache_key(request.model_dump())
        r = await get_redis()
        try:
            cached = await r.get(f"ai:cache:{cache_key}")
            if cached:
                data = json.loads(cached)
                data["cached"] = True
                return CompletionResponse(**data)
        finally:
            await r.aclose()

    # Resolve provider list from Constitution
    matcher = get_matcher()
    try:
        providers = matcher.resolve_with_fallback(
            capability_id=request.capability,
            workflow_id=request.workflow_id,
        )
    except CapabilityNotFound:
        raise HTTPException(status_code=400, detail=f"Capability not found: {request.capability}")
    except NoHealthyProvider:
        raise HTTPException(
            status_code=503, detail=f"No healthy providers for capability: {request.capability}"
        )

    if not providers:
        raise HTTPException(status_code=503, detail="No providers available")

    last_error = None
    result = None
    used_provider = None

    for provider in providers:
        if request.model_preference and provider.id != request.model_preference:
            continue

        cb = _get_cb(provider.id)
        if cb.is_open():
            print(f"[AI-GATEWAY] Circuit open for {provider.id}, skipping")
            continue

        try:
            config = matcher.get_provider_config(provider.id)
            result = await call_provider(
                provider.plugin_id,
                config,
                request.prompt,
                request.max_tokens,
                request.temperature,
            )
            cb.record_success()
            matcher.update_health(provider.id, True)
            used_provider = provider
            break
        except Exception as e:
            last_error = e
            cb.record_failure()
            print(f"[AI-GATEWAY] Provider {provider.id} failed: {e}")
            matcher.update_health(provider.id, False)
            continue

    if not result or not used_provider:
        raise HTTPException(
            status_code=503,
            detail=f"All providers failed. Last error: {last_error}",
        )

    # Cost calculation
    cost_model = used_provider.cost
    cost = cost_model.get("per_request", 0.0)
    if "per_input_token" in cost_model:
        cost += result.get("tokens_input", 0) / 1000 * cost_model["per_input_token"]
    if "per_output_token" in cost_model:
        cost += result.get("tokens_output", 0) / 1000 * cost_model["per_output_token"]

    duration_ms = int((time.time() - start_time) * 1000)

    response = CompletionResponse(
        text=result["text"],
        model_used=used_provider.config.get("model", "unknown"),
        provider=used_provider.id,
        tokens_input=result.get("tokens_input", 0),
        tokens_output=result.get("tokens_output", 0),
        cost_usd=cost,
        cached=False,
        duration_ms=duration_ms,
    )

    # Cache write
    if request.use_cache:
        cache_key = get_cache_key(request.model_dump())
        r = await get_redis()
        try:
            await r.setex(
                f"ai:cache:{cache_key}",
                3600,
                json.dumps(response.model_dump(exclude={"cached"})),
            )
        finally:
            await r.aclose()

    # Cost tracking
    r = await get_redis()
    try:
        await r.incrbyfloat(f"ai:cost:{used_provider.id}:today", cost)
        await r.incrby(f"ai:tokens:{used_provider.id}:input:today", result.get("tokens_input", 0))
        await r.incrby(
            f"ai:tokens:{used_provider.id}:output:today", result.get("tokens_output", 0)
        )
    finally:
        await r.aclose()

    return response


# ---------------------------------------------------------------------------
# Info endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/capabilities")
async def list_capabilities():
    """List all capabilities from the Constitution."""
    matcher = get_matcher()
    return matcher.list_capabilities()


@app.get("/v1/providers/{capability_id}")
async def get_providers(capability_id: str):
    """Get all providers for a capability, ordered by priority."""
    try:
        matcher = get_matcher()
        providers = matcher.resolve_with_fallback(capability_id)
        return [
            {
                "id": p.id,
                "name": p.name,
                "priority": p.priority,
                "healthy": p.healthy,
                "fallback_enabled": p.fallback_enabled,
                "cost": p.cost,
                "circuit_open": _get_cb(p.id).is_open(),
            }
            for p in providers
        ]
    except CapabilityNotFound:
        raise HTTPException(status_code=404, detail=f"Capability not found: {capability_id}")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-gateway", "version": "2.1.0"}
