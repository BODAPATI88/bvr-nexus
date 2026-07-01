async def health_check(config: dict) -> dict:
    """Echo stub is always healthy — no external dependency."""
    return {"status": "healthy", "latency_ms": 0.0}
