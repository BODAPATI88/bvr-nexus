"""
BVR AI Gateway v2.1 — Uses Capability Matcher for provider selection.
Reads the Constitution for declared priorities, not hardcoded fallbacks.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import httpx
import os
import json
import hashlib
import redis.asyncio as redis
import sys

# Add bvr-sdk to path
sys.path.insert(0, "/app/bvr-sdk")
from bvr_sdk import get_matcher, CapabilityNotFound, NoHealthyProvider

app = FastAPI(title="BVR AI Gateway", version="2.1.0")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

async def get_redis():
    return await redis.from_url(REDIS_URL, decode_responses=True)

def get_cache_key(req: dict) -> str:
    """Generate cache key from request."""
    key_data = f"{req.get('capability')}:{req.get('prompt')}:{req.get('model_preference')}:{req.get('max_tokens')}:{req.get('temperature')}"
    return hashlib.sha256(key_data.encode()).hexdigest()

class CompletionRequest(BaseModel):
    capability: str = Field(..., description="Required capability: code, reasoning, analysis, creative, summarization")
    prompt: str = Field(..., description="The prompt text")
    model_preference: Optional[str] = Field(None, description="Preferred provider ID from Constitution")
    max_tokens: int = Field(4000, ge=1, le=32000)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    use_cache: bool = Field(True, description="Whether to use response caching")
    stream: bool = Field(False, description="Whether to stream response")
    workflow_id: Optional[str] = Field(None, description="Optional workflow ID for per-workflow overrides")

class CompletionResponse(BaseModel):
    text: str
    model_used: str
    provider: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    cached: bool = False
    duration_ms: Optional[int] = None

async def call_provider(provider_id: str, config: dict, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
    """Call a provider via its plugin."""
    from bvr_sdk import get_registry

    registry = get_registry()
    plugin = registry.get_plugin(provider_id)

    if not plugin or not plugin.get("worker_module"):
        raise ValueError(f"Provider plugin not found: {provider_id}")

    execute_func = getattr(plugin["worker_module"], "execute")
    return await execute_func(
        config,
        {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system_prompt": ""
        }
    )

@app.post("/v1/completions", response_model=CompletionResponse)
async def completions(request: CompletionRequest):
    """
    Main completion endpoint using Capability Matcher for provider selection.

    The Capability Matcher reads the Constitution at boot and knows:
    - Which providers implement each capability
    - Their priority order
    - Their health status
    - Their cost models

    This endpoint simply asks the Matcher: "give me the best provider for code_analysis"
    and the Matcher returns the highest-priority healthy provider.
    """
    import time
    start_time = time.time()

    # Check cache
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
            await r.close()

    # Use Capability Matcher to resolve provider
    matcher = get_matcher()

    try:
        # Resolve with fallback chain for cascading retries
        providers = matcher.resolve_with_fallback(
            capability_id=request.capability,
            workflow_id=request.workflow_id
        )
    except CapabilityNotFound:
        raise HTTPException(status_code=400, detail=f"Capability not found: {request.capability}")
    except NoHealthyProvider:
        raise HTTPException(status_code=503, detail=f"No healthy providers for capability: {request.capability}")

    if not providers:
        raise HTTPException(status_code=503, detail="No providers available")

    # Try providers in priority order
    last_error = None
    result = None
    used_provider = None

    for provider in providers:
        # Skip if preferred provider specified and this isn't it
        if request.model_preference and provider.id != request.model_preference:
            continue

        try:
            config = matcher.get_provider_config(provider.id)
            result = await call_provider(
                provider.id,
                config,
                request.prompt,
                request.max_tokens,
                request.temperature
            )
            used_provider = provider
            break
        except Exception as e:
            last_error = e
            print(f"[AI-GATEWAY] Provider {provider.id} failed: {e}")
            # Mark provider unhealthy for this request
            matcher.update_health(provider.id, False)
            continue

    if not result or not used_provider:
        raise HTTPException(
            status_code=503,
            detail=f"All providers failed. Last error: {last_error}"
        )

    # Calculate cost from Constitution cost model
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

    # Cache result
    if request.use_cache:
        cache_key = get_cache_key(request.model_dump())
        r = await get_redis()
        try:
            await r.setex(
                f"ai:cache:{cache_key}",
                3600,
                json.dumps(response.model_dump(exclude={"cached"}))
            )
        finally:
            await r.close()

    # Track cost
    r = await get_redis()
    try:
        await r.incrbyfloat(f"ai:cost:{used_provider.id}:today", cost)
        await r.incrby(f"ai:tokens:{used_provider.id}:input:today", result.get("tokens_input", 0))
        await r.incrby(f"ai:tokens:{used_provider.id}:output:today", result.get("tokens_output", 0))
    finally:
        await r.close()

    return response

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
            }
            for p in providers
        ]
    except CapabilityNotFound:
        raise HTTPException(status_code=404, detail=f"Capability not found: {capability_id}")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-gateway", "version": "2.1.0"}
