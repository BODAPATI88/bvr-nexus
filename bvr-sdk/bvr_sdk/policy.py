import os
import httpx
from typing import Dict, Any

OPA_URL = os.getenv("OPA_URL", "http://localhost:8181")
BVR_API_URL = os.getenv("BVR_API_URL", "http://localhost:8000")

async def check_policy(policy_path: str, input_data: Dict[str, Any]) -> bool:
    """
    Evaluate a policy against input data using OPA.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{OPA_URL}/v1/data/{policy_path}",
            json={"input": input_data},
            timeout=10.0
        )
        if resp.status_code == 200:
            result = resp.json()
            return result.get("result", False)
        return False

async def require_approval(
    action: str,
    resource: str,
    approvers: list[str],
    timeout_minutes: int = 30
) -> bool:
    """
    Require human approval before proceeding.
    Creates an approval request in the database and waits for response.
    Returns True if approved, False if denied or timed out.
    """
    import uuid
    from datetime import datetime, timedelta

    approval_id = str(uuid.uuid4())

    # Create approval request in BVR API
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BVR_API_URL}/api/v1/approvals",
            json={
                "approval_id": approval_id,
                "action": action,
                "resource": resource,
                "approvers": approvers,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(minutes=timeout_minutes)).isoformat(),
            },
            timeout=10.0
        )
        if resp.status_code != 200:
            print(f"[APPROVAL] Failed to create approval request: {resp.status_code}")
            return False

    print(f"[APPROVAL] Request {approval_id} created for {action} on {resource}")
    print(f"[APPROVAL] Waiting for approval from: {', '.join(approvers)}")

    # Poll for approval status
    import asyncio
    for _ in range(timeout_minutes * 2):  # Poll every 30 seconds
        await asyncio.sleep(30)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BVR_API_URL}/api/v1/approvals/{approval_id}",
                timeout=10.0
            )
            if resp.status_code == 200:
                status = resp.json().get("status")
                if status == "approved":
                    print(f"[APPROVAL] ✅ Approved by {resp.json().get('approved_by')}")
                    return True
                elif status == "denied":
                    print(f"[APPROVAL] ❌ Denied by {resp.json().get('denied_by')}")
                    return False

    # Timeout
    print(f"[APPROVAL] ⏰ Timed out after {timeout_minutes} minutes")
    return False
