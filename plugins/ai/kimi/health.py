import httpx

async def health_check(config: dict) -> dict:
    """Check Moonshot Kimi API health."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.moonshot.cn/v1/models",
                headers={"Authorization": f"Bearer {config['api_key']}"},
                timeout=10.0
            )
            if resp.status_code == 200:
                return {"status": "healthy", "latency_ms": resp.elapsed.total_seconds() * 1000}
            return {"status": "degraded", "code": resp.status_code}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
