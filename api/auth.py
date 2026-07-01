"""
BVR API authentication and authorisation.

Extracted from api/main.py so auth logic can be tested in isolation.

Key design decisions:
- Keycloak public key is cached (TTL=BVR_JWKS_CACHE_TTL, default 5 min) to
  avoid an HTTP round-trip on every request (H2).
- On Keycloak unavailability, the stale cached key is served so in-flight
  JWTs continue to validate during brief outages.
- BVR_SERVICE_TOKEN is a hard fallback for service-to-service calls.
"""

import os
import time
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
_KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "bvr")
_JWKS_CACHE_TTL = int(os.getenv("BVR_JWKS_CACHE_TTL", "300"))  # seconds

# Module-level cache: { realm_url -> {"public_key": str, "fetched_at": float} }
_jwks_cache: Dict[str, Any] = {}

security = HTTPBearer()


async def _fetch_keycloak_public_key(realm_url: str) -> Optional[str]:
    """Return the Keycloak RSA public key, using a TTL cache.

    Falls back to the stale cached value if Keycloak is temporarily
    unreachable, so requests don't fail during brief Keycloak restarts.
    """
    import httpx as _httpx

    now = time.time()
    entry = _jwks_cache.get(realm_url)

    if entry and now - entry["fetched_at"] < _JWKS_CACHE_TTL:
        return entry["public_key"]

    try:
        async with _httpx.AsyncClient() as client:
            resp = await client.get(realm_url, timeout=5.0)
            if resp.status_code == 200:
                public_key = resp.json().get("public_key", "")
                if public_key:
                    _jwks_cache[realm_url] = {"public_key": public_key, "fetched_at": now}
                    return public_key
    except Exception:
        pass

    # Keycloak unreachable — serve stale key if available
    if entry:
        return entry["public_key"]
    return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """Validate a Bearer token and return the decoded claims.

    Tries Keycloak JWT validation first (with cached public key), then
    falls back to the service token for internal service-to-service calls.
    """
    token = credentials.credentials
    realm_url = f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}"

    public_key = await _fetch_keycloak_public_key(realm_url)
    if public_key:
        try:
            decoded = jwt.decode(
                token,
                key=f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----",
                algorithms=["RS256"],
                audience="bvr-api",
                options={"verify_exp": True},
            )
            return decoded
        except jwt.PyJWTError:
            pass

    # Fallback: service token for machine-to-machine calls
    service_token = os.getenv("BVR_SERVICE_TOKEN")
    if service_token and token == service_token:
        return {"sub": "bvr-service", "roles": ["bvr-service"]}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
    )


async def require_role(role: str):
    """Dependency factory for role-based access control."""

    async def _check_role(user: Dict[str, Any] = Depends(get_current_user)):
        roles = user.get("roles", [])
        if role not in roles and "bvr-admin" not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {role}",
            )
        return user

    return _check_role
