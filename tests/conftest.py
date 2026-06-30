"""
Shared test configuration and SDK stubs.

bvr_sdk/__init__.py imports heavy optional dependencies (minio, jwt, opentelemetry)
that are not installed in the test environment. We stub the SDK package before
any test module imports it, then wire in the real sub-modules we actually want
to test (events.py, registry.py) on top of the stubs.
"""

import sys
import types
import importlib
import importlib.util
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# 1. Create lightweight stub packages for uninstalled / external libraries
# ---------------------------------------------------------------------------

def _make_stub(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# minio
minio_mod = _make_stub("minio", Minio=MagicMock())

# jwt (PyJWT)
_make_stub("jwt", decode=MagicMock(), ExpiredSignatureError=Exception, InvalidTokenError=Exception)

# opentelemetry — the whole namespace tree
for _pkg in [
    "opentelemetry",
    "opentelemetry.trace",
    "opentelemetry.sdk",
    "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.resources",
    "opentelemetry.exporter",
    "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.instrumentation",
    "opentelemetry.instrumentation.fastapi",
    "opentelemetry.instrumentation.httpx",
]:
    _make_stub(_pkg)

# Give opentelemetry.trace a no-op get_tracer so telemetry.py doesn't crash
sys.modules["opentelemetry.trace"].get_tracer = lambda *a, **kw: MagicMock()

# yaml
_make_stub("yaml")

# ---------------------------------------------------------------------------
# 2. Register bvr-sdk on sys.path and pre-load the real sub-modules we test
# ---------------------------------------------------------------------------

SDK_ROOT = "/home/user/bvr-nexus/bvr-sdk"
WORKERS_ROOT = "/home/user/bvr-nexus"

if SDK_ROOT not in sys.path:
    sys.path.insert(0, SDK_ROOT)
if WORKERS_ROOT not in sys.path:
    sys.path.insert(0, WORKERS_ROOT)


def _load_module_directly(dotted_name: str, file_path: str) -> types.ModuleType:
    """Load a single .py file as a named module, bypassing package __init__."""
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the real events module directly (no __init__.py side-effects)
events_mod = _load_module_directly(
    "bvr_sdk.events",
    f"{SDK_ROOT}/bvr_sdk/events.py",
)

# Load the real registry module directly
registry_mod = _load_module_directly(
    "bvr_sdk.registry",
    f"{SDK_ROOT}/bvr_sdk/registry.py",
)

# ---------------------------------------------------------------------------
# 3. Build a minimal bvr_sdk package stub that exposes only what BaseWorker needs
# ---------------------------------------------------------------------------

bvr_sdk_pkg = types.ModuleType("bvr_sdk")
bvr_sdk_pkg.EventEnvelope = events_mod.EventEnvelope
bvr_sdk_pkg.emit_event = events_mod.emit_event
bvr_sdk_pkg.subscribe = events_mod.subscribe
bvr_sdk_pkg.wait_for_event = events_mod.wait_for_event
bvr_sdk_pkg.register_worker = registry_mod.register_worker

# Remaining symbols BaseWorker imports — stub as no-ops
bvr_sdk_pkg.trace_span = lambda name: (lambda f: f)          # pass-through decorator
bvr_sdk_pkg.check_policy = AsyncMock(return_value=True)
bvr_sdk_pkg.ai_gateway_call = AsyncMock(return_value={})
bvr_sdk_pkg.upload_artifact = AsyncMock(return_value="http://minio/artifact")
bvr_sdk_pkg.get_registry = MagicMock(return_value=MagicMock())

sys.modules["bvr_sdk"] = bvr_sdk_pkg
