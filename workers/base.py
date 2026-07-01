"""
Base worker class for BVR Nexus.
All workers inherit from this.
"""

import asyncio
import os
import signal
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from bvr_sdk import (
    EventEnvelope,
    ai_gateway_call,
    check_policy,
    clear_failure_counter,
    emit_event,
    get_registry,
    register_worker,
    send_to_dlq,
    subscribe,
    trace_span,
    track_failure,
    upload_artifact,
)

BVR_API_URL = os.getenv("BVR_API_URL", "http://localhost:8000")
MAX_RETRIES = int(os.getenv("BVR_MAX_EVENT_RETRIES", "3"))


def _verify_plugin_manifest(plugin_dir: str, plugin_id: str) -> None:
    import hashlib, yaml as _yaml
    manifest_path = os.path.join(plugin_dir, "manifest.yaml")
    if not os.path.exists(manifest_path):
        raise RuntimeError(f"Plugin {plugin_id}: missing manifest.yaml")
    raw = open(manifest_path, "rb").read()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    print(f"[PLUGIN] {plugin_id} manifest SHA256: {actual_sha256}")
    try:
        manifest = _yaml.safe_load(raw)
        expected = manifest.get("manifest_sha256")
        if expected and expected != actual_sha256:
            raise RuntimeError(
                f"Plugin {plugin_id}: manifest SHA256 mismatch "
                f"(expected {expected}, got {actual_sha256})"
            )
    except Exception as exc:
        if "mismatch" in str(exc):
            raise
        # yaml not available or parse error — log and continue
        print(f"[PLUGIN] {plugin_id}: manifest verification skipped ({exc})")


class BaseWorker(ABC):
    """Base class for all BVR workers."""

    worker_id: str = "base"
    capabilities: List[str] = []
    version: str = "2.0.0"

    def __init__(self):
        self.plugin_cache = {}

    async def start(self):
        """Register and start consuming events with graceful shutdown."""
        shutdown_event = asyncio.Event()

        # asyncio-safe signal handling — does not call sys.exit()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: (
                    print(f"\n[WORKER] Received signal {s.name}, shutting down gracefully..."),
                    shutdown_event.set(),
                ),
            )

        await register_worker(
            worker_id=self.worker_id,
            capabilities=self.capabilities,
            health_endpoint=f"/health/{self.worker_id}",
            version=self.version,
        )
        print(f"[WORKER] {self.worker_id} registered and ready")

        # One consumer group per worker type: every event type reaches every
        # worker type independently (fanout), filtered cheaply inside subscribe().
        await subscribe(
            event_types=self.capabilities,
            consumer_group=f"bvr-{self.worker_id}",
            consumer_name=self.worker_id,
            handler=self._handle_event,
            shutdown_event=shutdown_event,
        )

    async def _handle_event(self, event: EventEnvelope):
        """Wrapper around handle() with telemetry, error handling, and DLQ tracking."""
        consumer_group = f"bvr-{self.worker_id}"
        try:
            await check_policy(
                "bvr.allow",
                {
                    "action": event.event_type,
                    "user": event.user_id,
                    "target": str(event.payload),
                },
            )

            result = await self.handle(event)

            artifact_url = result.pop("artifact_url", None)
            artifact_urls = [artifact_url] if artifact_url else None
            await self._post_result(event.event_id, "completed", result, artifact_urls)

            await emit_event(
                event_type=f"{event.event_type}.completed",
                payload=result,
                correlation_id=event.correlation_id,
            )

            # Clear the failure counter on a successful run
            await clear_failure_counter(event.event_id, consumer_group)

        except Exception as e:
            print(f"[ERROR] Worker {self.worker_id} failed on {event.event_id}: {e}")
            await self._post_result(event.event_id, "failed", {"error": str(e)})

            # Track consecutive failures; move to DLQ after MAX_RETRIES
            count = await track_failure(event.event_id, consumer_group)
            if count >= MAX_RETRIES:
                print(
                    f"[DLQ] Event {event.event_id} exceeded {MAX_RETRIES} retries,"
                    f" sending to DLQ"
                )
                await send_to_dlq(event, consumer_group, str(e))

    async def _post_result(
        self,
        event_id: str,
        status: str,
        result: Dict[str, Any],
        artifact_urls: List[str] = None,
    ):
        """POST the execution result back to the BVR API."""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BVR_API_URL}/api/v1/events/{event_id}/result",
                    json={
                        "event_id": event_id,
                        "status": status,
                        "result": result,
                        "artifact_urls": artifact_urls,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                    timeout=10.0,
                )
        except Exception as e:
            print(f"[WARN] Failed to post result for {event_id}: {e}", flush=True)

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
