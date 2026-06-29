"""
AI Gateway client — Unified interface to all LLM providers.
Provides fallback, cost tracking, caching.
"""

import os
import json
import hashlib
from typing import Optional, Dict, Any
import httpx
import redis.asyncio as redis

AI_GATEWAY_URL = os.getenv("AI_GATEWAY_URL", "http://localhost:8001")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

async def get_redis():
    return await redis.from_url(REDIS_URL, decode_responses=True)

async def ai_gateway_call(
    capability: str,
    prompt: str,
    model_preference: Optional[str] = None,
    max_tokens: int = 4000,
    temperature: float = 0.7,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Call AI Gateway for LLM inference.

    Args:
        capability: What the model should do (code, reasoning, creative)
        prompt: The prompt text
        model_preference: Preferred model (claude, gpt, kimi, ollama)
        max_tokens: Max output tokens
        temperature: Sampling temperature
        use_cache: Whether to use response cache

    Returns:
        Dict with text, model_used, tokens_input, tokens_output, cost_usd
    """
    # Check cache
    if use_cache:
        cache_key = hashlib.sha256(f"{capability}:{prompt}:{model_preference}".encode()).hexdigest()
        r = await get_redis()
        try:
            cached = await r.get(f"bvr:ai_cache:{cache_key}")
            if cached:
                return json.loads(cached)
        finally:
            await r.close()

    # Call AI Gateway
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{AI_GATEWAY_URL}/v1/completions",
            json={
                "capability": capability,
                "prompt": prompt,
                "model_preference": model_preference,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=120.0
        )
        resp.raise_for_status()
        result = resp.json()

    # Cache result
    if use_cache:
        r = await get_redis()
        try:
            await r.setex(
                f"bvr:ai_cache:{cache_key}",
                3600,  # 1 hour TTL
                json.dumps(result)
            )
        finally:
            await r.close()

    return result

async def track_tokens(
    model_id: str,
    tokens_input: int,
    tokens_output: int
) -> float:
    """Track token usage and return cost."""
    # In production: lookup cost from registry, store in DB
    cost_per_1k = 0.003  # Default
    cost = (tokens_input + tokens_output) / 1000 * cost_per_1k

    # Store in Redis for real-time tracking
    r = await get_redis()
    try:
        await r.incrbyfloat(f"bvr:cost:{model_id}:today", cost)
    finally:
        await r.close()

    return cost

async def cache_response(prompt: str, response: str, ttl: int = 3600):
    """Manually cache an AI response."""
    cache_key = hashlib.sha256(prompt.encode()).hexdigest()
    r = await get_redis()
    try:
        await r.setex(f"bvr:ai_cache:{cache_key}", ttl, response)
    finally:
        await r.close()
