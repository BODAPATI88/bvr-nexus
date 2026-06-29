"""
BVR SDK — Standardized interface for all BVR workers.
Every worker imports from here.
"""

from .events import EventEnvelope, emit_event, subscribe, wait_for_event
from .auth import get_token, verify_permission
from .storage import upload_artifact, download_artifact, list_artifacts
from .ai import ai_gateway_call, track_tokens, cache_response
from .telemetry import trace_span, log_metric, log_event, init_telemetry
from .retry import with_retry, with_timeout, with_circuit_breaker
from .policy import check_policy, require_approval
from .registry import register_worker, discover_integration, discover_model
from .plugin_registry import get_registry, PluginRegistry
from .capability_matcher import get_matcher, CapabilityMatcher, CapabilityNotFound, NoHealthyProvider
from .integration_loader import get_loader, IntegrationLoader

__version__ = "2.0.0"

__all__ = [
    # Events
    "EventEnvelope", "emit_event", "subscribe", "wait_for_event",
    # Auth
    "get_token", "verify_permission",
    # Storage
    "upload_artifact", "download_artifact", "list_artifacts",
    # AI
    "ai_gateway_call", "track_tokens", "cache_response",
    # Telemetry
    "trace_span", "log_metric", "log_event", "init_telemetry",
    # Retry
    "with_retry", "with_timeout", "with_circuit_breaker",
    # Policy
    "check_policy", "require_approval",
    # Registry
    "register_worker", "discover_integration", "discover_model",
    "get_registry", "PluginRegistry",
    "get_matcher", "CapabilityMatcher", "CapabilityNotFound", "NoHealthyProvider",
    "get_loader", "IntegrationLoader",
]
