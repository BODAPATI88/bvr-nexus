import httpx

async def health_check(config: dict) -> dict:
    """Check GitHub API health."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/rate_limit",
                headers={"Authorization": f"token {config.get('token', '')}"},
                timeout=10.0
            )
            if resp.status_code == 200:
                data = resp.json()
                remaining = data["resources"]["core"]["remaining"]
                return {
                    "status": "healthy",
                    "rate_limit_remaining": remaining,
                    "latency_ms": resp.elapsed.total_seconds() * 1000
                }
            return {"status": "degraded", "code": resp.status_code}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
