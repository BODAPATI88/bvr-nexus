# BVR Nexus — Plugin Development Guide

---

## Overview

Every external integration in BVR Nexus is a self-describing plugin. Plugins are auto-discovered at worker startup, verified by SHA256 manifest hash, and executed only after OPA policy approval.

Plugin location: `plugins/<category>/<name>/`

---

## Required File Structure

```
plugins/
└── <category>/
    └── <name>/
        ├── __init__.py       # empty — required for auto-discovery
        ├── manifest.yaml     # identity, capabilities, version
        ├── schema.yaml       # typed input/output contract
        ├── permissions.yaml  # required secrets (via Vault)
        ├── health.py         # async health_check(config) → dict
        └── worker.py         # execute(config, inputs) → dict
                              # stream_execute(config, inputs) → AsyncGenerator
```

All six files are required. The auto-discovery scanner will skip a plugin if any file is missing.

---

## manifest.yaml

```yaml
id: plugins.ai.my-provider
name: My Provider
category: ai
version: 1.0.0
description: Integrates My Provider LLM API
capabilities:
  - code_analysis
  - content_generation
dependencies:
  - httpx>=0.27.0
author: BVR Platform Team
manifest_sha256: ""    # leave empty; SHA256 is computed at load time
```

The `capabilities` list must match capability names declared in `contracts/constitution.yaml`. If a capability is not in the constitution, the AI Gateway will never route to this plugin.

---

## schema.yaml

Defines the typed input and output contract. Workers validate inputs against this schema before calling the plugin.

```yaml
input:
  type: object
  required:
    - prompt
    - capability
  properties:
    prompt:
      type: string
      description: The prompt text to send to the provider
    capability:
      type: string
      enum: [code_analysis, content_generation, research]
    max_tokens:
      type: integer
      default: 4096
    temperature:
      type: number
      default: 0.7
      minimum: 0.0
      maximum: 2.0
    model_preference:
      type: string
      description: Hint to the AI Gateway; may be overridden by constitution

output:
  type: object
  properties:
    content:
      type: string
      description: Generated text content
    usage:
      type: object
      properties:
        input_tokens:
          type: integer
        output_tokens:
          type: integer
    model:
      type: string
      description: Actual model used
    provider:
      type: string
```

---

## permissions.yaml

Lists the Vault secret paths this plugin requires. Workers retrieve these secrets via the BVR SDK before calling the plugin.

```yaml
secrets:
  - key: MY_PROVIDER_API_KEY
    vault_path: vault://secrets/my-provider/api-key
    description: API key for My Provider
    required: true

  - key: MY_PROVIDER_ORG_ID
    vault_path: vault://secrets/my-provider/org-id
    description: Organization ID (optional)
    required: false
```

---

## health.py

The health check is called during worker startup and by the registry's health polling.

```python
async def health_check(config: dict) -> dict:
    """Return health status for this plugin."""
    import httpx

    api_key = config.get("MY_PROVIDER_API_KEY", "")
    if not api_key:
        return {"status": "unhealthy", "reason": "MY_PROVIDER_API_KEY not set"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.myprovider.com/health",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            return {"status": "healthy"}
        return {"status": "degraded", "http_status": resp.status_code}
    except Exception as exc:
        return {"status": "unhealthy", "reason": str(exc)}
```

---

## worker.py

Two entry points are required: `execute` for standard call-and-response, and `stream_execute` for SSE token streaming.

```python
async def execute(config: dict, inputs: dict) -> dict:
    """Execute a single completion request."""
    import httpx

    api_key = config["MY_PROVIDER_API_KEY"]
    prompt = inputs["prompt"]
    max_tokens = inputs.get("max_tokens", 4096)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.myprovider.com/v1/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "my-model-v1",
                "prompt": prompt,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "content": data["choices"][0]["text"],
        "usage": {
            "input_tokens": data["usage"]["prompt_tokens"],
            "output_tokens": data["usage"]["completion_tokens"],
        },
        "model": data["model"],
        "provider": "my-provider",
    }


async def stream_execute(config: dict, inputs: dict):
    """Stream tokens as they are generated (AsyncGenerator)."""
    import httpx

    api_key = config["MY_PROVIDER_API_KEY"]
    prompt = inputs["prompt"]

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            "https://api.myprovider.com/v1/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "my-model-v1", "prompt": prompt, "stream": True},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    import json
                    chunk = json.loads(payload)
                    yield chunk["choices"][0].get("delta", {}).get("content", "")
```

---

## Registering the Provider in the Constitution

After creating the plugin, add it to `contracts/constitution.yaml`:

```yaml
capabilities:
  code_analysis:
    providers:
      - id: claude_code
        plugin: plugins.ai.claude
        priority: 1
      - id: gpt_code
        plugin: plugins.ai.gpt
        priority: 2
      - id: my_provider_code        # new entry
        plugin: plugins.ai.my-provider
        priority: 3
      - id: ollama_code
        plugin: plugins.ai.ollama
        priority: 4
```

The AI Gateway reads this file at startup. No code changes are needed — the Capability Matcher routes to the new plugin automatically based on priority.

---

## Adding an API Key

Add a placeholder to `.env.example`:

```bash
MY_PROVIDER_API_KEY=           # API key for My Provider
```

Add the variable to `k8s/create-secrets.sh`:

```bash
--from-literal=MY_PROVIDER_API_KEY="${MY_PROVIDER_API_KEY:-}" \
```

---

## Testing a Plugin

```python
import asyncio
from plugins.ai.my_provider.worker import execute
from plugins.ai.my_provider.health import health_check

config = {"MY_PROVIDER_API_KEY": "test-key"}
inputs = {"prompt": "Hello world", "capability": "code_analysis"}

# Health check
result = asyncio.run(health_check(config))
assert result["status"] in ("healthy", "degraded")

# Execute
result = asyncio.run(execute(config, inputs))
assert "content" in result
assert "usage" in result
```

For unit tests in the test suite, mock the `httpx.AsyncClient` calls:

```python
from unittest.mock import AsyncMock, patch
import pytest

@pytest.mark.asyncio
async def test_execute_returns_content():
    mock_resp = AsyncMock()
    mock_resp.json.return_value = {
        "choices": [{"text": "Hello from mock"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "model": "my-model-v1",
    }
    mock_resp.raise_for_status = lambda: None

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        result = await execute(
            config={"MY_PROVIDER_API_KEY": "k"},
            inputs={"prompt": "test", "capability": "code_analysis"},
        )

    assert result["content"] == "Hello from mock"
    assert result["usage"]["input_tokens"] == 10
```

---

## Bundled Plugins (Reference)

| Plugin | Path | Category | Capabilities |
|--------|------|----------|--------------|
| Claude (Anthropic) | `plugins/ai/claude/` | ai | code_analysis, content_generation, research |
| GPT (OpenAI) | `plugins/ai/gpt/` | ai | code_analysis, content_generation, research |
| Kimi (Moonshot) | `plugins/ai/kimi/` | ai | code_analysis, content_generation, research |
| Echo | `plugins/ai/echo/` | ai | testing, development |
| GitHub | `plugins/code/github/` | code | repository_access, pull_requests, issues |
| Slack | `plugins/productivity/slack/` | productivity | notifications, messaging |
