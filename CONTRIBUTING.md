# Contributing to BVR Nexus

## Getting Started

```bash
git clone <repo-url>
cd bvr-nexus
cp .env.example .env && make secrets   # generates placeholder secrets
make start                             # starts the full Docker stack
# add real API keys to .env:
#   ANTHROPIC_API_KEY, OPENAI_API_KEY, KIMI_API_KEY, GITHUB_TOKEN, SLACK_WEBHOOK_URL
```

## Development Workflow

**Branch naming:**
- `feature/<short-description>` — new capability
- `fix/<short-description>` — bug fix
- `refactor/<short-description>` — code restructuring, no behavior change
- `chore/<short-description>` — dependencies, tooling, config

**Before pushing:**
```bash
make lint                              # ruff + black --check + mypy — must pass
python -m pytest tests/ -q            # must stay green
```

**Testing requirements:**
- Every new worker needs a unit test in `tests/workers/`
- Every new OPA policy needs `opa test governance/rego/`
- Mock all SDK calls at the function level (`bvr_sdk.ai_gateway_call`, `bvr_sdk.emit_event`, etc.)

**LLM calls — mandatory:**
```python
# CORRECT — goes through fallback, cost tracking, governance
from bvr_sdk import ai_gateway_call

result = await ai_gateway_call(capability="code_analysis", prompt="...")

# WRONG — bypasses AI Gateway
import anthropic
```

Never import provider SDKs (`anthropic`, `openai`, etc.) directly inside workers.

## Architecture Rules

Full rules are in [CLAUDE.md](CLAUDE.md). The three non-negotiable invariants:

1. **Kestra orchestrates** — Kestra workflows contain only HTTP tasks, waits, retries, and notifications. Never business logic or LLM calls.
2. **Workers execute — only through BVR SDK** — workers import from `bvr_sdk`, `workers.base`, and stdlib only. No direct provider imports.
3. **AI Gateway abstracts all LLM providers** — all LLM calls use `bvr_sdk.ai_gateway_call()`. Provider priority is declared in `contracts/constitution.yaml`, not in worker code.
