"""
Base worker class for BVR Nexus.
All workers inherit from this.
"""

import asyncio
import os
import signal
import sys
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from bvr_sdk import (
    EventEnvelope, emit_event, subscribe,
    trace_span, register_worker, check_policy,
    ai_gateway_call, upload_artifact,
    get_registry
)

class BaseWorker(ABC):
    """Base class for all BVR workers."""

    worker_id: str = "base"
    capabilities: List[str] = []
    version: str = "2.0.0"

    def __init__(self):
        self.plugin_cache = {}

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGTERM/SIGINT."""
        def signal_handler(signum, frame):
            print(f"\n[WORKER] Received signal {signum}, shutting down gracefully...")
            self._shutting_down = True
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    async def start(self):
        self._setup_signal_handlers()
        self._shutting_down = False
        """Register and start consuming events."""
        await register_worker(
            worker_id=self.worker_id,
            capabilities=self.capabilities,
            health_endpoint=f"/health/{self.worker_id}",
            version=self.version
        )
        print(f"[WORKER] {self.worker_id} registered and ready")

        # Subscribe to events — one group per worker type so every event
        # reaches every worker type independently (fanout), with filtering
        # inside subscribe() discarding non-matching event types cheaply.
        await subscribe(
            event_types=self.capabilities,
            consumer_group=f"bvr-{self.worker_id}",
            consumer_name=self.worker_id,
            handler=self._handle_event
        )

    async def _handle_event(self, event: EventEnvelope):
        """Wrapper around handle() with telemetry and error handling."""
        try:
            await check_policy("bvr.allow", {
                "action": event.event_type,
                "user": event.user_id,
                "target": str(event.payload)
            })

            result = await self.handle(event)

            # Emit completion event
            await emit_event(
                event_type=f"{event.event_type}.completed",
                payload=result,
                correlation_id=event.correlation_id
            )
        except Exception as e:
            print(f"[ERROR] Worker {self.worker_id} failed: {e}")
            await emit_event(
                event_type=f"{event.event_type}.failed",
                payload={"error": str(e)},
                correlation_id=event.correlation_id
            )

    @abstractmethod
    async def handle(self, event: EventEnvelope) -> Dict[str, Any]:
        """Implement in subclass."""
        pass

    @property
    def registry(self):
        """Get the plugin registry (auto-discovery)."""
        return get_registry()

    def plugin(self, plugin_id: str):
        """Get a plugin by ID from the auto-discovered registry."""
        return self.registry.get_plugin(plugin_id)
