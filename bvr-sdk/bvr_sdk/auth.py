"""
Real Authentication and Authorization — Keycloak + Vault integration.
No more stubs.
"""

import os
import httpx
import jwt
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "bvr")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "bvr-api")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
VAULT_URL = os.getenv("VAULT_URL", "http://vault:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")

# In-memory token cache (use Redis in production)
_token_cache: Dict[str, Any] = {}

async def get_service_token() -> str:
    """Get Keycloak client credentials token for service-to-service calls."""
    cache_key = "service_token"

    # Check cache
    if cache_key in _token_cache:
        cached = _token_cache[cache_key]
        if cached["expires_at"] > datetime.utcnow():
            return cached["token"]

    # Fetch new token from Keycloak
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
            },
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()

        token = data["access_token"]
        expires_in = data.get("expires_in", 300)

        _token_cache[cache_key] = {
            "token": token,
            "expires_at": datetime.utcnow() + timedelta(seconds=expires_in - 60)
        }

        return token

async def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a JWT token and return decoded claims."""
    try:
        # Fetch Keycloak public key
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
                timeout=10.0
            )
            resp.raise_for_status()
            realm_info = resp.json()
            public_key = realm_info["public_key"]

        # Verify token
        decoded = jwt.decode(
            token,
            key=f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----",
            algorithms=["RS256"],
            audience=KEYCLOAK_CLIENT_ID,
            options={"verify_exp": True}
        )

        return decoded
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None

async def verify_permission(user_id: str, action: str, resource: str) -> bool:
    """
    Verify user has permission for action on resource.
    Checks Keycloak roles AND OPA policy.
    """
    # Check Keycloak roles
    async with httpx.AsyncClient() as client:
        service_token = await get_service_token()
        resp = await client.get(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/role-mappings",
            headers={"Authorization": f"Bearer {service_token}"},
            timeout=10.0
        )
        if resp.status_code != 200:
            return False

        roles = resp.json()
        role_names = [r["name"] for r in roles.get("realmMappings", [])]

        # Check if user has required role
        required_role = _action_to_role(action)
        if required_role not in role_names:
            return False

    # Also check OPA policy
    from .policy import check_policy
    return await check_policy("bvr/allow", {
        "user": user_id,
        "action": action,
        "resource": resource,
        "roles": role_names
    })

def _action_to_role(action: str) -> str:
    """Map action to required role."""
    role_map = {
        "review": "bvr-operator",
        "research": "bvr-operator", 
        "achieve": "bvr-operator",
        "admin": "bvr-admin",
    }
    return role_map.get(action.split(".")[0], "bvr-operator")

async def get_secret(secret_path: str) -> str:
    """Retrieve secret from Vault KV v2."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VAULT_URL}/v1/secret/data/{secret_path}",
            headers={"X-Vault-Token": VAULT_TOKEN},
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["data"]["data"]["value"]
        raise ValueError(f"Secret not found: {secret_path} (status: {resp.status_code})")

async def create_user(username: str, email: str, password: str, roles: List[str]) -> str:
    """Create a user in Keycloak."""
    service_token = await get_service_token()

    async with httpx.AsyncClient() as client:
        # Create user
        resp = await client.post(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
            headers={"Authorization": f"Bearer {service_token}"},
            json={
                "username": username,
                "email": email,
                "enabled": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}]
            },
            timeout=10.0
        )
        resp.raise_for_status()

        # Get user ID from Location header
        user_id = resp.headers["Location"].split("/")[-1]

        # Assign roles
        for role in roles:
            await client.post(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/role-mappings/realm",
                headers={"Authorization": f"Bearer {service_token}"},
                json=[{"name": role}],
                timeout=10.0
            )

        return user_id

# Backward compatibility
async def get_token() -> str:
    """Compatibility wrapper for older SDK imports."""
    return await get_service_token()

