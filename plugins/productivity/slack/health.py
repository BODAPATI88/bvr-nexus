import httpx

async def health_check(config: dict) -> dict:
    """Check Slack API health."""
    try:
        token = config.get("token", "")
        if not token:
            return {"status": "degraded", "reason": "no token configured"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            data = resp.json()
            if data.get("ok"):
                return {
                    "status": "healthy",
                    "team": data.get("team"),
                    "latency_ms": resp.elapsed.total_seconds() * 1000
                }
            return {"status": "degraded", "error": data.get("error")}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
