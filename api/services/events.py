"""Event service — all asyncpg operations for the events domain."""

import json
from typing import Optional, List
import asyncpg


class EventService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def store_event(
        self,
        event_id: str,
        event_type: str,
        payload: dict,
        correlation_id: str,
        source: str,
        priority: str,
        user_id: Optional[str],
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events
                    (event_id, event_type, payload, correlation_id, source, priority, user_id, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
                """,
                event_id,
                event_type,
                json.dumps(payload),
                correlation_id,
                source,
                priority,
                user_id,
            )

    async def get_result(self, event_id: str) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT e.event_id, e.status, r.result, r.artifact_urls, r.metrics,
                       e.timestamp AS created_at, r.updated_at
                FROM events e
                LEFT JOIN event_results r ON e.event_id = r.event_id
                WHERE e.event_id = $1
                """,
                event_id,
            )
        return dict(row) if row else None

    async def post_result(
        self,
        event_id: str,
        status: str,
        result: Optional[dict],
        artifact_urls: Optional[List[str]],
        metrics: Optional[dict],
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO event_results (event_id, result, artifact_urls, metrics, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (event_id) DO UPDATE SET
                        result        = EXCLUDED.result,
                        artifact_urls = EXCLUDED.artifact_urls,
                        metrics       = EXCLUDED.metrics,
                        updated_at    = NOW()
                    """,
                    event_id,
                    json.dumps(result) if result is not None else None,
                    json.dumps(artifact_urls) if artifact_urls is not None else None,
                    json.dumps(metrics) if metrics is not None else None,
                )
                await conn.execute(
                    "UPDATE events SET status = $1 WHERE event_id = $2",
                    status,
                    event_id,
                )

    async def post_webhook_result(
        self,
        correlation_id: str,
        status: str,
        result: Optional[dict],
        artifact_urls: Optional[List[str]],
        metrics: Optional[dict],
    ) -> None:
        """Kestra webhook path: look up by correlation_id, not event_id."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO event_results (event_id, result, artifact_urls, metrics, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (event_id) DO UPDATE SET
                        result        = EXCLUDED.result,
                        artifact_urls = EXCLUDED.artifact_urls,
                        metrics       = EXCLUDED.metrics,
                        updated_at    = NOW()
                    """,
                    correlation_id,
                    json.dumps(result) if result is not None else None,
                    json.dumps(artifact_urls) if artifact_urls is not None else None,
                    json.dumps(metrics) if metrics is not None else None,
                )
                await conn.execute(
                    "UPDATE events SET status = $1 WHERE correlation_id = $2",
                    status,
                    correlation_id,
                )
