import httpx
from typing import Dict, Any

async def execute(config: dict, inputs: dict) -> Dict[str, Any]:
    """Execute Moonshot Kimi completion (OpenAI-compatible API)."""
    messages = []
    system_prompt = inputs.get("system_prompt", "")
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": inputs["prompt"]})

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.get("model", "moonshot-v1-128k"),
                "max_tokens": inputs.get("max_tokens", 4000),
                "temperature": inputs.get("temperature", 0.7),
                "messages": messages,
            },
            timeout=120.0
        )
        resp.raise_for_status()
        data = resp.json()

        tokens_input = data["usage"]["prompt_tokens"]
        tokens_output = data["usage"]["completion_tokens"]

        return {
            "text": data["choices"][0]["message"]["content"],
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": (
                tokens_input / 1000 * 0.001 +
                tokens_output / 1000 * 0.005
            ),
            "model": config.get("model", "moonshot-v1-128k"),
        }
