"""Registry service — asyncpg operations for the platform registry."""

from typing import List
import asyncpg


class RegistryService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def register_worker(
        self,
        worker_id: str,
        capabilities: List[str],
        health_endpoint: str,
        version: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workers (worker_id, capabilities, health_endpoint, version, last_seen, status)
                VALUES ($1, $2, $3, $4, NOW(), 'active')
                ON CONFLICT (worker_id) DO UPDATE SET
                    capabilities    = EXCLUDED.capabilities,
                    health_endpoint = EXCLUDED.health_endpoint,
                    version         = EXCLUDED.version,
                    last_seen       = NOW()
                """,
                worker_id,
                capabilities,
                health_endpoint,
                version,
            )

    async def list_workers(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM workers")
        return [dict(r) for r in rows]

    async def register_integration(
        self,
        id: str,
        name: str,
        type_: str,
        version: str,
        capabilities: List[str],
        status: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO integrations (id, name, type, version, capabilities, status)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    name         = EXCLUDED.name,
                    version      = EXCLUDED.version,
                    capabilities = EXCLUDED.capabilities,
                    status       = EXCLUDED.status
                """,
                id,
                name,
                type_,
                version,
                capabilities,
                status,
            )

    async def list_integrations(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM integrations")
        return [dict(r) for r in rows]
