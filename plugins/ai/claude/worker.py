import json
import httpx
from typing import AsyncGenerator, Dict, Any

async def execute(config: dict, inputs: dict) -> Dict[str, Any]:
    """Execute Claude completion."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config["api_key"],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": config.get("model", "claude-sonnet-4"),
                "max_tokens": inputs.get("max_tokens", 4000),
                "temperature": inputs.get("temperature", 0.7),
                "system": inputs.get("system_prompt", ""),
                "messages": [{"role": "user", "content": inputs["prompt"]}],
            },
            timeout=120.0
        )
        resp.raise_for_status()
        data = resp.json()

        return {
            "text": data["content"][0]["text"],
            "tokens_input": data["usage"]["input_tokens"],
            "tokens_output": data["usage"]["output_tokens"],
            "cost_usd": (
                data["usage"]["input_tokens"] / 1000 * 0.003 +
                data["usage"]["output_tokens"] / 1000 * 0.015
            ),
            "model": config.get("model", "claude-sonnet-4"),
        }


async def stream_execute(config: dict, inputs: dict) -> AsyncGenerator[str, None]:
    """Stream Claude completion via SSE."""
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config["api_key"],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": config.get("model", "claude-sonnet-4"),
                "max_tokens": inputs.get("max_tokens", 4000),
                "temperature": inputs.get("temperature", 0.7),
                "system": inputs.get("system_prompt", ""),
                "messages": [{"role": "user", "content": inputs["prompt"]}],
                "stream": True,
            },
            timeout=120.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line == "data: [DONE]":
                    break
                if line.startswith("event: message_stop"):
                    break
                if line.startswith("data: "):
                    payload = line[len("data: "):]
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("delta", {})
                    if data.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
