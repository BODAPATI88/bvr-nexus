"""
Event system — EventEnvelope, emit, subscribe, wait.
Uses Redis Streams for lightweight messaging.
"""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from pydantic import BaseModel, Field
import redis.asyncio as redis
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    payload: Dict[str, Any]
    correlation_id: str
    source: str = "worker"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    priority: str = "normal"
    user_id: Optional[str] = None

async def get_redis():
    return await redis.from_url(REDIS_URL, decode_responses=True)

async def emit_event(
    event_type: str,
    payload: Dict[str, Any],
    correlation_id: str,
    priority: str = "normal",
    user_id: Optional[str] = None
) -> EventEnvelope:
    """Emit an event to the BVR event bus."""
    event = EventEnvelope(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
        priority=priority,
        user_id=user_id
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
            }
        )
    finally:
        await r.close()

    return event

async def subscribe(
    event_types: list[str],
    consumer_group: str,
    consumer_name: str,
    handler: Callable[[EventEnvelope], Any]
):
    """Subscribe to events from Redis Streams."""
    r = await get_redis()
    try:
        # Create consumer group if not exists
        try:
            await r.xgroup_create("bvr:events", consumer_group, id="0", mkstream=True)
        except redis.ResponseError:
            pass  # Group already exists

        while True:
            messages = await r.xreadgroup(
                consumer_group,
                consumer_name,
                {"bvr:events": ">"},
                count=1,
                block=5000
            )

            if messages:
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        event = EventEnvelope(
                            event_id=fields["event_id"],
                            event_type=fields["event_type"],
                            payload=json.loads(fields["payload"]),
                            correlation_id=fields["correlation_id"],
                            priority=fields.get("priority", "normal"),
                        )
                        try:
                            await handler(event)
                            await r.xack("bvr:events", consumer_group, msg_id)
                        except Exception as e:
                            # Log error, don't ack — message will be redelivered
                            print(f"Error processing event {event.event_id}: {e}")
    finally:
        await r.close()

async def wait_for_event(
    correlation_id: str,
    event_type: str,
    timeout: int = 300
) -> Optional[EventEnvelope]:
    """Wait for a specific event by correlation_id and type."""
    r = await get_redis()
    try:
        # Simple polling with Redis keys
        # In production: use pub/sub or blocking xread
        for _ in range(timeout):
            result = await r.get(f"bvr:result:{correlation_id}:{event_type}")
            if result:
                data = json.loads(result)
                return EventEnvelope(**data)
            await asyncio.sleep(1)
        return None
    finally:
        await r.close()

import asyncio
