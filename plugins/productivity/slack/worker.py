import httpx
from typing import Dict, Any

async def execute(config: dict, inputs: dict) -> Dict[str, Any]:
    """Send Slack message."""
    webhook_url = config.get("webhook_url")
    channel = inputs.get("channel", "#general")
    text = inputs["text"]

    if webhook_url:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                webhook_url,
                json={"text": text, "channel": channel},
                timeout=10.0
            )
            resp.raise_for_status()

    return {
        "result": "sent",
        "channel": channel,
        "text_preview": text[:100],
    }
