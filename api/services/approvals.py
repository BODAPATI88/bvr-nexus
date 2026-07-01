"""Approvals service — asyncpg operations for the approval workflow."""

from typing import List, Optional
import asyncpg


class ApprovalService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create_approval(
        self,
        approval_id: str,
        action: str,
        resource: str,
        approvers: List[str],
        status: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO approvals
                    (approval_id, action, resource, approvers, status, created_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                approval_id, action, resource, approvers, status, created_at, expires_at,
            )

    async def get_approval(self, approval_id: str) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM approvals WHERE approval_id = $1", approval_id
            )
        return dict(row) if row else None

    async def approve(self, approval_id: str, approver: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE approvals
                SET status = 'approved', approved_by = $1, approved_at = NOW()
                WHERE approval_id = $2
                """,
                approver, approval_id,
            )

    async def deny(self, approval_id: str, approver: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE approvals
                SET status = 'denied', denied_by = $1
                WHERE approval_id = $2
                """,
                approver, approval_id,
            )

    async def list_approvals(self, status: Optional[str] = None) -> List[dict]:
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM approvals WHERE status = $1 ORDER BY created_at DESC",
                    status,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM approvals ORDER BY created_at DESC"
                )
        return [dict(r) for r in rows]
