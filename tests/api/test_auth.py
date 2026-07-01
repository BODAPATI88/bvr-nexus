"""
Tests for api.auth — JWKS key caching, JWT validation, service token fallback.

All Keycloak HTTP calls are patched; no running Keycloak is required.
"""

import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load api/auth.py directly with a unique dotted name so the stubs injected
# here don't bleed into other test modules that use the real jwt library.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()

# Stub jwt before loading api/auth.py
_jwt_stub = types.ModuleType("jwt")
_jwt_stub.PyJWTError = Exception


class _FakePyJWTError(Exception):
    pass


_jwt_stub.PyJWTError = _FakePyJWTError
sys.modules.setdefault("jwt", _jwt_stub)

_auth_spec = importlib.util.spec_from_file_location(
    "_test_api_auth", str(_REPO_ROOT / "api" / "auth.py")
)
_auth_mod = importlib.util.module_from_spec(_auth_spec)
_auth_spec.loader.exec_module(_auth_mod)

_fetch_keycloak_public_key = _auth_mod._fetch_keycloak_public_key
_jwks_cache = _auth_mod._jwks_cache
get_current_user = _auth_mod.get_current_user
_JWKS_CACHE_TTL = _auth_mod._JWKS_CACHE_TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_cache():
    _jwks_cache.clear()


def _fake_httpx_client(status_code: int = 200, public_key: str = "FAKE_KEY"):
    """Return a context-manager mock for httpx.AsyncClient."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value={"public_key": public_key})

    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# _fetch_keycloak_public_key
# ---------------------------------------------------------------------------

class TestFetchKeycloakPublicKey:
    @pytest.fixture(autouse=True)
    def clear(self):
        _clear_cache()
        yield
        _clear_cache()

    async def test_returns_key_on_200(self):
        client = _fake_httpx_client(200, "MYKEY")
        with patch("httpx.AsyncClient", return_value=client):
            key = await _fetch_keycloak_public_key("http://kc/realms/bvr")
        assert key == "MYKEY"

    async def test_key_stored_in_cache(self):
        client = _fake_httpx_client(200, "CACHED_KEY")
        with patch("httpx.AsyncClient", return_value=client):
            await _fetch_keycloak_public_key("http://kc/realms/bvr")
        assert _jwks_cache["http://kc/realms/bvr"]["public_key"] == "CACHED_KEY"

    async def test_cached_key_returned_within_ttl(self):
        client = _fake_httpx_client(200, "FIRST_KEY")
        with patch("httpx.AsyncClient", return_value=client):
            await _fetch_keycloak_public_key("http://kc/realms/bvr")

        # Second call should NOT hit the network
        client2 = _fake_httpx_client(200, "SECOND_KEY")
        with patch("httpx.AsyncClient", return_value=client2):
            key = await _fetch_keycloak_public_key("http://kc/realms/bvr")

        assert key == "FIRST_KEY"
        client2.get.assert_not_awaited()

    async def test_expired_cache_refetches(self):
        url = "http://kc/realms/bvr"
        _jwks_cache[url] = {"public_key": "OLD_KEY", "fetched_at": time.time() - _JWKS_CACHE_TTL - 1}

        client = _fake_httpx_client(200, "NEW_KEY")
        with patch("httpx.AsyncClient", return_value=client):
            key = await _fetch_keycloak_public_key(url)

        assert key == "NEW_KEY"

    async def test_returns_none_when_keycloak_unreachable_and_no_cache(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=client):
            key = await _fetch_keycloak_public_key("http://kc/realms/bvr")

        assert key is None

    async def test_returns_stale_key_when_keycloak_unreachable(self):
        url = "http://kc/realms/bvr"
        # Pre-load an expired (stale) cache entry
        _jwks_cache[url] = {"public_key": "STALE_KEY", "fetched_at": time.time() - _JWKS_CACHE_TTL - 1}

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=client):
            key = await _fetch_keycloak_public_key(url)

        assert key == "STALE_KEY"

    async def test_non_200_response_does_not_cache(self):
        client = _fake_httpx_client(503, "SHOULD_NOT_CACHE")
        with patch("httpx.AsyncClient", return_value=client):
            key = await _fetch_keycloak_public_key("http://kc/realms/bvr")

        assert key is None
        assert "http://kc/realms/bvr" not in _jwks_cache

    async def test_empty_public_key_not_cached(self):
        client = _fake_httpx_client(200, "")
        with patch("httpx.AsyncClient", return_value=client):
            key = await _fetch_keycloak_public_key("http://kc/realms/bvr")

        assert key is None
        assert "http://kc/realms/bvr" not in _jwks_cache


# ---------------------------------------------------------------------------
# get_current_user — service token fallback
# ---------------------------------------------------------------------------

class TestGetCurrentUserServiceToken:
    @pytest.fixture(autouse=True)
    def clear(self):
        _clear_cache()
        yield
        _clear_cache()

    async def test_valid_service_token_accepted(self, monkeypatch):
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "svc-tok")

        # Keycloak unreachable — no public key
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=Exception("unreachable"))

        creds = MagicMock()
        creds.credentials = "svc-tok"

        with patch("httpx.AsyncClient", return_value=client):
            result = await get_current_user(creds)

        assert result["sub"] == "bvr-service"
        assert "bvr-service" in result["roles"]

    async def test_wrong_service_token_raises_401(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setenv("BVR_SERVICE_TOKEN", "correct-token")

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=Exception("unreachable"))

        creds = MagicMock()
        creds.credentials = "wrong-token"

        with pytest.raises(HTTPException) as exc_info:
            with patch("httpx.AsyncClient", return_value=client):
                await get_current_user(creds)

        assert exc_info.value.status_code == 401

    async def test_no_service_token_env_raises_401(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.delenv("BVR_SERVICE_TOKEN", raising=False)

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=Exception("unreachable"))

        creds = MagicMock()
        creds.credentials = "any-token"

        with pytest.raises(HTTPException) as exc_info:
            with patch("httpx.AsyncClient", return_value=client):
                await get_current_user(creds)

        assert exc_info.value.status_code == 401

    async def test_valid_jwt_accepted_when_keycloak_available(self, monkeypatch):
        decoded_claims = {"sub": "user-123", "roles": ["bvr-user"]}

        # Patch the jwt module reference inside _auth_mod to control decode()
        jwt_stub = MagicMock()
        jwt_stub.decode = MagicMock(return_value=decoded_claims)
        jwt_stub.PyJWTError = _FakePyJWTError

        with patch.object(_auth_mod, "_fetch_keycloak_public_key", AsyncMock(return_value="VALID_PUB_KEY")):
            with patch.object(_auth_mod, "jwt", jwt_stub):
                creds = MagicMock()
                creds.credentials = "valid.jwt.token"
                result = await get_current_user(creds)

        assert result["sub"] == "user-123"

    async def test_invalid_jwt_falls_through_to_service_token(self, monkeypatch):
        monkeypatch.setenv("BVR_SERVICE_TOKEN", "svc")

        jwt_stub = MagicMock()
        jwt_stub.decode = MagicMock(side_effect=_FakePyJWTError("bad"))
        jwt_stub.PyJWTError = _FakePyJWTError

        with patch.object(_auth_mod, "_fetch_keycloak_public_key", AsyncMock(return_value="SOME_KEY")):
            with patch.object(_auth_mod, "jwt", jwt_stub):
                creds = MagicMock()
                creds.credentials = "svc"
                result = await get_current_user(creds)

        assert result["sub"] == "bvr-service"
