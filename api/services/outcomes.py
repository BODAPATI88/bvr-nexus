"""Outcomes service — asyncpg operations for outcome metrics."""

from typing import List, Optional
import asyncpg


class OutcomeService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def register_outcome(
        self,
        goal_id: str,
        description: str,
        metric: str,
        target: float,
        unit: str,
        current: Optional[float],
        workflow_id: str,
        status: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO outcomes
                    (goal_id, description, metric, target, unit, current, workflow_id, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (goal_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    metric      = EXCLUDED.metric,
                    target      = EXCLUDED.target,
                    unit        = EXCLUDED.unit,
                    current     = EXCLUDED.current,
                    workflow_id = EXCLUDED.workflow_id,
                    status      = EXCLUDED.status
                """,
                goal_id, description, metric, target,
                unit, current, workflow_id, status,
            )

    async def list_outcomes(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM outcomes")
        return [dict(r) for r in rows]
