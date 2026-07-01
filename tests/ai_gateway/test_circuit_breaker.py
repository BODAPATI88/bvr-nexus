"""
Tests for the CircuitBreaker class in ai-gateway/main.py.

The CircuitBreaker is loaded via importlib so we avoid importing the full
FastAPI app (which requires Redis, bvr-sdk, etc. at import time).
"""

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Load CircuitBreaker without executing the full FastAPI app
# ---------------------------------------------------------------------------

GATEWAY_FILE = Path(__file__).parent.parent.parent / "ai-gateway" / "main.py"


def _load_circuit_breaker():
    """
    Extract and compile only the CircuitBreaker class from ai-gateway/main.py.

    We do this by reading the source, isolating the class definition, and
    exec-ing it into a minimal namespace — avoiding the need for FastAPI,
    Redis, prometheus_client, or bvr_sdk to be installed.
    """
    source = GATEWAY_FILE.read_text()

    # Build a namespace that satisfies the module-level imports that
    # CircuitBreaker actually uses at runtime (only `time` and `Optional`).
    import time
    from typing import Optional

    namespace: dict = {
        "time": time,
        "Optional": Optional,
    }

    # Compile and exec the entire file in a controlled namespace.
    # Imports that aren't available will raise ImportError; we stub them out.
    stub_modules = {
        "redis": types.ModuleType("redis"),
        "redis.asyncio": types.ModuleType("redis.asyncio"),
        "fastapi": types.ModuleType("fastapi"),
        "prometheus_client": types.ModuleType("prometheus_client"),
        "pydantic": types.ModuleType("pydantic"),
    }
    # Give fastapi stub the names used at module level
    fastapi_stub = stub_modules["fastapi"]
    fastapi_stub.FastAPI = lambda **kw: None  # type: ignore[attr-defined]
    fastapi_stub.HTTPException = Exception  # type: ignore[attr-defined]
    fastapi_stub.Response = object  # type: ignore[attr-defined]
    fastapi_responses_stub = types.ModuleType("fastapi.responses")
    fastapi_responses_stub.StreamingResponse = object  # type: ignore[attr-defined]
    stub_modules["fastapi.responses"] = fastapi_responses_stub

    pydantic_stub = stub_modules["pydantic"]
    pydantic_stub.BaseModel = object  # type: ignore[attr-defined]
    pydantic_stub.Field = lambda *a, **kw: None  # type: ignore[attr-defined]

    prometheus_stub = stub_modules["prometheus_client"]
    prometheus_stub.CONTENT_TYPE_LATEST = ""  # type: ignore[attr-defined]
    prometheus_stub.generate_latest = lambda: b""  # type: ignore[attr-defined]

    # bvr_sdk is imported via sys.path manipulation; stub it too
    bvr_sdk_stub = types.ModuleType("bvr_sdk")
    bvr_sdk_stub.CapabilityNotFound = Exception  # type: ignore[attr-defined]
    bvr_sdk_stub.NoHealthyProvider = Exception  # type: ignore[attr-defined]
    bvr_sdk_stub.get_matcher = lambda: None  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {**stub_modules, "bvr_sdk": bvr_sdk_stub}):
        spec = importlib.util.spec_from_file_location("ai_gateway_main", GATEWAY_FILE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Suppress the sys.path.insert that points at /app/bvr-sdk
        module.__dict__["__builtins__"] = __builtins__
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            pass  # FastAPI app instantiation may fail; CircuitBreaker is defined before that

    return module.CircuitBreaker


CircuitBreaker = _load_circuit_breaker()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

THRESHOLD = 3
TIMEOUT = 60


def make_breaker(threshold: int = THRESHOLD, recovery_timeout: int = TIMEOUT) -> object:
    return CircuitBreaker(failure_threshold=threshold, recovery_timeout=recovery_timeout)


def open_breaker(cb) -> None:
    """Drive the breaker to the open state."""
    for _ in range(cb.failure_threshold):
        cb.record_failure()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_new_breaker_is_closed():
    """A freshly created circuit breaker should be closed."""
    cb = make_breaker()
    assert cb.is_open() is False


def test_does_not_open_below_threshold():
    """Recording fewer failures than the threshold must keep the breaker closed."""
    cb = make_breaker(threshold=THRESHOLD)
    for _ in range(THRESHOLD - 1):
        cb.record_failure()
    assert cb.is_open() is False


def test_opens_at_threshold():
    """Recording exactly `threshold` failures must open the breaker."""
    cb = make_breaker(threshold=THRESHOLD)
    open_breaker(cb)
    assert cb.is_open() is True


def test_success_resets_closed():
    """record_success on an open breaker must close it."""
    cb = make_breaker(threshold=THRESHOLD)
    open_breaker(cb)
    assert cb.is_open() is True  # sanity
    cb.record_success()
    assert cb.is_open() is False


def test_half_open_after_recovery_timeout():
    """After recovery_timeout elapses, is_open() returns False (half-open probe allowed)."""
    cb = make_breaker(threshold=THRESHOLD, recovery_timeout=TIMEOUT)
    open_breaker(cb)
    assert cb.is_open() is True  # sanity

    # Simulate time advancing past the recovery window
    future_time = cb._opened_at + TIMEOUT + 1
    with patch("time.time", return_value=future_time):
        result = cb.is_open()

    assert result is False


def test_failure_in_half_open_reopens():
    """A failure during the half-open probe must transition back to open."""
    cb = make_breaker(threshold=THRESHOLD, recovery_timeout=TIMEOUT)
    open_breaker(cb)

    # Advance past recovery timeout to trigger half-open transition
    future_time = cb._opened_at + TIMEOUT + 1
    with patch("time.time", return_value=future_time):
        cb.is_open()  # transitions to half-open

    # Simulate the probe failing
    cb.record_failure()
    assert cb.is_open() is True


def test_success_in_half_open_closes():
    """A success during the half-open probe must fully close the breaker."""
    cb = make_breaker(threshold=THRESHOLD, recovery_timeout=TIMEOUT)
    open_breaker(cb)

    # Advance past recovery timeout to trigger half-open transition
    future_time = cb._opened_at + TIMEOUT + 1
    with patch("time.time", return_value=future_time):
        cb.is_open()  # transitions to half-open

    # Simulate the probe succeeding
    cb.record_success()
    assert cb.is_open() is False
