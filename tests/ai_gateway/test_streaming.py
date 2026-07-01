"""
Tests for the /v1/stream SSE endpoint and stream_execute helpers.
All provider HTTP calls are mocked.
"""

import importlib.util
import json
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
CLAUDE_WORKER = REPO_ROOT / "plugins" / "ai" / "claude" / "worker.py"
GPT_WORKER = REPO_ROOT / "plugins" / "ai" / "gpt" / "worker.py"
KIMI_WORKER = REPO_ROOT / "plugins" / "ai" / "kimi" / "worker.py"
GATEWAY_FILE = REPO_ROOT / "ai-gateway" / "main.py"


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------

def _load_plugin(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_gateway_circuit_breaker():
    """Load CircuitBreaker from ai-gateway/main.py without starting FastAPI."""
    stub_modules = {
        "redis": types.ModuleType("redis"),
        "redis.asyncio": types.ModuleType("redis.asyncio"),
        "fastapi": types.ModuleType("fastapi"),
        "fastapi.responses": types.ModuleType("fastapi.responses"),
        "prometheus_client": types.ModuleType("prometheus_client"),
        "pydantic": types.ModuleType("pydantic"),
    }

    fastapi_stub = stub_modules["fastapi"]
    fastapi_stub.FastAPI = lambda **kw: None  # type: ignore[attr-defined]
    fastapi_stub.HTTPException = Exception  # type: ignore[attr-defined]
    fastapi_stub.Response = object  # type: ignore[attr-defined]

    fastapi_responses_stub = stub_modules["fastapi.responses"]
    fastapi_responses_stub.StreamingResponse = object  # type: ignore[attr-defined]

    pydantic_stub = stub_modules["pydantic"]
    pydantic_stub.BaseModel = object  # type: ignore[attr-defined]
    pydantic_stub.Field = lambda *a, **kw: None  # type: ignore[attr-defined]

    prometheus_stub = stub_modules["prometheus_client"]
    prometheus_stub.CONTENT_TYPE_LATEST = ""  # type: ignore[attr-defined]
    prometheus_stub.generate_latest = lambda: b""  # type: ignore[attr-defined]

    bvr_sdk_stub = types.ModuleType("bvr_sdk")
    bvr_sdk_stub.CapabilityNotFound = Exception  # type: ignore[attr-defined]
    bvr_sdk_stub.NoHealthyProvider = Exception  # type: ignore[attr-defined]
    bvr_sdk_stub.get_matcher = lambda: None  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {**stub_modules, "bvr_sdk": bvr_sdk_stub}):
        spec = importlib.util.spec_from_file_location("ai_gateway_main", GATEWAY_FILE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        module.__dict__["__builtins__"] = __builtins__
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            pass

    return module.CircuitBreaker


CircuitBreaker = _load_gateway_circuit_breaker()


# ---------------------------------------------------------------------------
# Helpers: build a mock httpx.AsyncClient that streams SSE lines
# ---------------------------------------------------------------------------

def _make_mock_httpx_client(lines: list[str]):
    """
    Return a mock that replaces httpx.AsyncClient.

    The workers use both:
      async with httpx.AsyncClient() as client:       (outer)
      async with client.stream(...) as resp:           (inner)

    We build nested async context managers so both work without real HTTP.
    """

    async def mock_aiter_lines():
        for line in lines:
            yield line

    # The streaming response object
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = mock_aiter_lines

    # Inner context manager: client.stream(...)
    @asynccontextmanager
    async def mock_stream(*args, **kwargs):
        yield mock_response

    # The client object returned by entering `async with httpx.AsyncClient()`
    mock_client_instance = MagicMock()
    mock_client_instance.stream = mock_stream

    # Outer context manager: httpx.AsyncClient()
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return mock_client_instance

        async def __aexit__(self, *args):
            pass

    return MockAsyncClient


# ---------------------------------------------------------------------------
# Load provider modules
# ---------------------------------------------------------------------------

claude = _load_plugin(CLAUDE_WORKER, "claude_worker")
gpt = _load_plugin(GPT_WORKER, "gpt_worker")
kimi = _load_plugin(KIMI_WORKER, "kimi_worker")


# ---------------------------------------------------------------------------
# SSE line fixtures
# ---------------------------------------------------------------------------

_CLAUDE_DELTA = json.dumps(
    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}
)
_CLAUDE_DELTA_AFTER = json.dumps(
    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "AFTER"}}
)
_GPT_DELTA = json.dumps({"choices": [{"delta": {"content": "World"}}]})
_KIMI_DELTA = json.dumps({"choices": [{"delta": {"content": "Kimi chunk"}}]})


# ---------------------------------------------------------------------------
# Claude tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claude_stream_execute_yields_text():
    """Claude stream_execute yields text from content_block_delta lines."""
    lines = [
        f"data: {_CLAUDE_DELTA}",
        "data: [DONE]",
    ]
    MockClient = _make_mock_httpx_client(lines)

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in claude.stream_execute(
            {"api_key": "test-key"}, {"prompt": "Hi"}
        ):
            chunks.append(chunk)

    assert chunks == ["Hello"]


@pytest.mark.asyncio
async def test_claude_stream_execute_stops_at_message_stop():
    """Claude stream_execute stops when it sees event: message_stop."""
    lines = [
        f"data: {_CLAUDE_DELTA}",
        "event: message_stop",
        # This line must never be reached
        f"data: {_CLAUDE_DELTA_AFTER}",
    ]
    MockClient = _make_mock_httpx_client(lines)

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in claude.stream_execute(
            {"api_key": "test-key"}, {"prompt": "Hi"}
        ):
            chunks.append(chunk)

    assert "AFTER" not in chunks
    assert chunks == ["Hello"]


# ---------------------------------------------------------------------------
# GPT tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gpt_stream_execute_yields_text():
    """GPT stream_execute yields content from choices[0].delta.content."""
    lines = [
        f"data: {_GPT_DELTA}",
        "data: [DONE]",
    ]
    MockClient = _make_mock_httpx_client(lines)

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in gpt.stream_execute(
            {"api_key": "test-key"}, {"prompt": "Hi"}
        ):
            chunks.append(chunk)

    assert chunks == ["World"]


# ---------------------------------------------------------------------------
# Kimi tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kimi_stream_execute_yields_text():
    """Kimi stream_execute yields content (same format as GPT/OpenAI)."""
    lines = [
        f"data: {_KIMI_DELTA}",
        "data: [DONE]",
    ]
    MockClient = _make_mock_httpx_client(lines)

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in kimi.stream_execute(
            {"api_key": "test-key"}, {"prompt": "Hi"}
        ):
            chunks.append(chunk)

    assert chunks == ["Kimi chunk"]


# ---------------------------------------------------------------------------
# Cross-provider edge-case tests (using GPT as representative)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_execute_skips_empty_chunks():
    """Lines with empty content string must not yield anything."""
    empty_delta = json.dumps({"choices": [{"delta": {"content": ""}}]})
    lines = [
        f"data: {empty_delta}",
        f"data: {_GPT_DELTA}",
        "data: [DONE]",
    ]
    MockClient = _make_mock_httpx_client(lines)

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in gpt.stream_execute(
            {"api_key": "test-key"}, {"prompt": "Hi"}
        ):
            chunks.append(chunk)

    # Only the non-empty chunk should appear
    assert chunks == ["World"]


@pytest.mark.asyncio
async def test_stream_execute_stops_at_done():
    """Generator must stop after [DONE] and not yield subsequent lines."""
    after_done = json.dumps({"choices": [{"delta": {"content": "AFTER DONE"}}]})
    lines = [
        f"data: {_GPT_DELTA}",
        "data: [DONE]",
        f"data: {after_done}",
    ]
    MockClient = _make_mock_httpx_client(lines)

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in gpt.stream_execute(
            {"api_key": "test-key"}, {"prompt": "Hi"}
        ):
            chunks.append(chunk)

    assert "AFTER DONE" not in chunks
    assert chunks == ["World"]
