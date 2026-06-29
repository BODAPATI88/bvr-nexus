"""
OpenTelemetry instrumentation for BVR workers.
Auto-tracing, metrics, and logging.
"""

import os
import functools
from typing import Callable, Any
from contextlib import asynccontextmanager

OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() == "true"

def init_telemetry(service_name: str):
    """Initialize OpenTelemetry for a worker service."""
    if not OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource

        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://jaeger:4317"))
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
    except ImportError:
        pass

def trace_span(name: str):
    """Decorator to trace a function."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not OTEL_ENABLED:
                return await func(*args, **kwargs)

            try:
                from opentelemetry import trace
                tracer = trace.get_tracer("bvr.sdk")
                with tracer.start_as_current_span(name):
                    return await func(*args, **kwargs)
            except ImportError:
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not OTEL_ENABLED:
                return func(*args, **kwargs)

            try:
                from opentelemetry import trace
                tracer = trace.get_tracer("bvr.sdk")
                with tracer.start_as_current_span(name):
                    return func(*args, **kwargs)
            except ImportError:
                return func(*args, **kwargs)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

async def log_metric(name: str, value: float, tags: dict = None):
    """Log a metric to Prometheus via push gateway or OTel."""
    # In production: use OTel metrics
    print(f"[METRIC] {name}={value} tags={tags}")

async def log_event(event_type: str, payload: dict):
    """Log a structured event."""
    print(f"[EVENT] {event_type}: {payload}")

import asyncio
