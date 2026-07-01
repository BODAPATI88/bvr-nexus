"""
Event system — EventEnvelope, emit, subscribe, wait.
Uses Redis Streams for lightweight messaging.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import redis.asyncio as redis
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MAX_RETRIES = int(os.getenv("BVR_MAX_EVENT_RETRIES", "3"))
_DLQ_STREAM = "bvr:events:dlq"
_IDEMPOTENCY_TTL = 86400  # 24 h


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    payload: Dict[str, Any]
    correlation_id: str
    source: str = "worker"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    priority: str = "normal"
    user_id: Optional[str] = None


async def get_redis() -> redis.Redis:
    return await redis.from_url(REDIS_URL, decode_responses=True)


async def emit_event(
    event_type: str,
    payload: Dict[str, Any],
    correlation_id: str,
    priority: str = "normal",
    user_id: Optional[str] = None,
) -> "EventEnvelope":
    """Emit an event to the BVR event bus."""
    event = EventEnvelope(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
        priority=priority,
        user_id=user_id,
    )

    r = await get_redis()
    try:
        await r.xadd(
            "bvr:events",
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "payload": json.dumps(event.payload),
                "correlation_id": event.correlation_id,
                "priority": event.priority,
                "timestamp": event.timestamp.isoformat(),
            },
        )
        # Notify any Kestra long-poll waiting on this correlation_id
        if event_type.endswith((".completed", ".failed")):
            await r.publish(
                f"bvr:webhook:{correlation_id}",
                json.dumps(
                    {
                        "correlation_id": correlation_id,
                        "event_type": event_type,
                        "status": "completed" if event_type.endswith(".completed") else "failed",
                        "result": payload,
                    }
                ),
            )
    finally:
        await r.aclose()

    return event


# ---------------------------------------------------------------------------
# Dead Letter Queue helpers
# ---------------------------------------------------------------------------

async def track_failure(event_id: str, consumer_group: str) -> int:
    """Increment the failure counter for this event+group. Returns new count."""
    key = f"bvr:failures:{event_id}:{consumer_group}"
    r = await get_redis()
    try:
        count = await r.incr(key)
        # Key expires after 7 days — long enough for manual inspection
        await r.expire(key, 604800)
        return count
    finally:
        await r.aclose()


async def clear_failure_counter(event_id: str, consumer_group: str) -> None:
    """Delete the failure counter after a successful execution."""
    key = f"bvr:failures:{event_id}:{consumer_group}"
    r = await get_redis()
    try:
        await r.delete(key)
    finally:
        await r.aclose()


async def send_to_dlq(
    event: "EventEnvelope",
    consumer_group: str,
    error: str,
) -> None:
    """Move a permanently-failed event to the Dead Letter Queue stream."""
    r = await get_redis()
    try:
        await r.xadd(
            _DLQ_STREAM,
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "payload": json.dumps(event.payload),
                "correlation_id": event.correlation_id,
                "consumer_group": consumer_group,
                "error": error,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    finally:
        await r.aclose()


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

async def subscribe(
    event_types: list[str],
    consumer_group: str,
    consumer_name: str,
    handler: Callable[["EventEnvelope"], Any],
    shutdown_event: Optional[asyncio.Event] = None,
) -> None:
    """Subscribe to events from Redis Streams.

    Exits cleanly when *shutdown_event* is set (checked between each batch).
    Idempotency: duplicate deliveries (same event_id + consumer_group) are
    silently ACK'd and skipped using a Redis NX key with a 24-hour TTL.
    """
    r = await get_redis()
    try:
        try:
            await r.xgroup_create("bvr:events", consumer_group, id="0", mkstream=True)
        except redis.ResponseError:
            pass  # Group already exists

        while True:
            if shutdown_event and shutdown_event.is_set():
                print(f"[SUBSCRIBE] {consumer_group} shutdown requested, exiting")
                break

            messages = await r.xreadgroup(
                consumer_group,
                consumer_name,
                {"bvr:events": ">"},
                count=1,
                block=5000,
            )

            if not messages:
                continue

            for _stream, msgs in messages:
                for msg_id, fields in msgs:
                    event = EventEnvelope(
                        event_id=fields["event_id"],
                        event_type=fields["event_type"],
                        payload=json.loads(fields["payload"]),
                        correlation_id=fields["correlation_id"],
                        priority=fields.get("priority", "normal"),
                    )

                    # Discard terminal/notification events and non-matching types
                    if event.event_type not in event_types or event.event_type.endswith(
                        (".completed", ".failed")
                    ):
                        await r.xack("bvr:events", consumer_group, msg_id)
                        continue

                    # Idempotency: skip duplicate deliveries
                    idem_key = f"bvr:idempotency:{event.event_id}:{consumer_group}"
                    acquired = await r.set(idem_key, "1", nx=True, ex=_IDEMPOTENCY_TTL)
                    if not acquired:
                        print(
                            f"[SUBSCRIBE] Duplicate delivery for {event.event_id}"
                            f" in {consumer_group}, skipping"
                        )
                        await r.xack("bvr:events", consumer_group, msg_id)
                        continue

                    try:
                        await handler(event)
                    except Exception as e:
                        print(f"Error processing event {event.event_id}: {e}")
                    finally:
                        # Always ACK — status is tracked in PostgreSQL.
                        await r.xack("bvr:events", consumer_group, msg_id)
    finally:
        await r.aclose()


async def wait_for_event(
    correlation_id: str,
    event_type: str,
    timeout: int = 300,
) -> Optional["EventEnvelope"]:
    """Wait for a specific event by correlation_id and type."""
    r = await get_redis()
    try:
        for _ in range(timeout):
            result = await r.get(f"bvr:result:{correlation_id}:{event_type}")
            if result:
                data = json.loads(result)
                return EventEnvelope(**data)
            await asyncio.sleep(1)
        return None
    finally:
        await r.aclose()
