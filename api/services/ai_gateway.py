"""AI Gateway service — asyncpg operations for models, prompts, and policies."""

from typing import List, Optional
import asyncpg


class AIGatewayService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def register_model(
        self,
        model_id: str,
        provider: str,
        model_name: str,
        capabilities: List[str],
        priority: int,
        fallback: Optional[str],
        cost_per_1k_input: float,
        cost_per_1k_output: float,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO models
                    (id, provider, model_name, capabilities, priority, fallback,
                     cost_per_1k_input, cost_per_1k_output)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    provider           = EXCLUDED.provider,
                    model_name         = EXCLUDED.model_name,
                    capabilities       = EXCLUDED.capabilities,
                    priority           = EXCLUDED.priority,
                    fallback           = EXCLUDED.fallback,
                    cost_per_1k_input  = EXCLUDED.cost_per_1k_input,
                    cost_per_1k_output = EXCLUDED.cost_per_1k_output
                """,
                model_id, provider, model_name, capabilities,
                priority, fallback, cost_per_1k_input, cost_per_1k_output,
            )

    async def list_models(self) -> List[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM models ORDER BY priority")
        return [dict(r) for r in rows]

    async def register_prompt(
        self,
        prompt_id: str,
        version: str,
        template: str,
        variables: List[str],
        model_preference: Optional[str],
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prompts (id, version, template, variables, model_preference)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    version          = EXCLUDED.version,
                    template         = EXCLUDED.template,
                    variables        = EXCLUDED.variables,
                    model_preference = EXCLUDED.model_preference
                """,
                prompt_id, version, template, variables, model_preference,
            )

    async def register_policy(
        self,
        policy_id: str,
        rego_path: str,
        description: str,
        applies_to: List[str],
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO policies (id, rego_path, description, applies_to)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (id) DO UPDATE SET
                    rego_path   = EXCLUDED.rego_path,
                    description = EXCLUDED.description,
                    applies_to  = EXCLUDED.applies_to
                """,
                policy_id, rego_path, description, applies_to,
            )
