"""
Tests for api.middleware — PayloadSizeMiddleware and ContentTypeMiddleware.

Middleware is exercised via a minimal FastAPI app so no Redis, Postgres,
or other infrastructure stubs are needed.
"""

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# Load api/middleware.py directly so this test file is immune to sys.modules
# stubs injected by test_events_endpoint.py (same pattern as test_services.py).
_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
_spec = importlib.util.spec_from_file_location(
    "_api_middleware", str(_REPO_ROOT / "api" / "middleware.py")
)
_middleware_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_middleware_mod)

MAX_PAYLOAD_BYTES = _middleware_mod.MAX_PAYLOAD_BYTES
PayloadSizeMiddleware = _middleware_mod.PayloadSizeMiddleware
ContentTypeMiddleware = _middleware_mod.ContentTypeMiddleware


# ---------------------------------------------------------------------------
# Fixture — minimal app with both middleware classes under test
# ---------------------------------------------------------------------------

def _make_app():
    app = FastAPI()
    app.add_middleware(PayloadSizeMiddleware)
    app.add_middleware(ContentTypeMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.json()
        return body

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.put("/update")
    async def update(request: Request):
        return {}

    @app.patch("/patch")
    async def patch_route(request: Request):
        return {}

    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_make_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# PayloadSizeMiddleware
# ---------------------------------------------------------------------------

class TestPayloadSizeMiddleware:
    def test_large_content_length_returns_413(self, client):
        oversized = MAX_PAYLOAD_BYTES + 1
        resp = client.post(
            "/echo",
            content=b"{}",
            headers={"content-type": "application/json", "content-length": str(oversized)},
        )
        assert resp.status_code == 413

    def test_413_body_is_json(self, client):
        oversized = MAX_PAYLOAD_BYTES + 1
        resp = client.post(
            "/echo",
            content=b"{}",
            headers={"content-type": "application/json", "content-length": str(oversized)},
        )
        assert resp.json()["detail"] == "Request body too large"

    def test_exact_limit_is_allowed(self, client):
        """Content-Length equal to the limit must not be rejected."""
        resp = client.post(
            "/echo",
            content=b'{"x":1}',
            headers={"content-type": "application/json", "content-length": str(MAX_PAYLOAD_BYTES)},
        )
        assert resp.status_code != 413

    def test_no_content_length_header_is_allowed(self, client):
        """Requests without Content-Length must pass through."""
        resp = client.post(
            "/echo",
            json={"key": "value"},
        )
        assert resp.status_code != 413

    def test_get_request_not_checked(self, client):
        resp = client.get("/ping")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ContentTypeMiddleware
# ---------------------------------------------------------------------------

class TestContentTypeMiddleware:
    def test_post_without_content_type_returns_415(self, client):
        resp = client.post(
            "/echo",
            content=b'{"x":1}',
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == 415

    def test_415_body_is_json(self, client):
        resp = client.post(
            "/echo",
            content=b'{}',
            headers={"content-type": "text/plain"},
        )
        data = resp.json()
        assert data["detail"] == "Content-Type must be application/json"

    def test_put_wrong_content_type_returns_415(self, client):
        resp = client.put(
            "/update",
            content=b'{}',
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 415

    def test_patch_wrong_content_type_returns_415(self, client):
        resp = client.patch(
            "/patch",
            content=b'{}',
            headers={"content-type": "multipart/form-data"},
        )
        assert resp.status_code == 415

    def test_post_with_json_content_type_passes(self, client):
        resp = client.post("/echo", json={"hello": "world"})
        assert resp.status_code == 200

    def test_content_type_with_charset_passes(self, client):
        """application/json; charset=utf-8 must be accepted."""
        resp = client.post(
            "/echo",
            content=b'{"a":1}',
            headers={"content-type": "application/json; charset=utf-8"},
        )
        assert resp.status_code == 200

    def test_get_without_content_type_passes(self, client):
        resp = client.get("/ping")
        assert resp.status_code == 200

    def test_missing_content_type_on_post_returns_415(self, client):
        resp = client.post(
            "/echo",
            content=b'{"x":1}',
            headers={"content-type": ""},
        )
        assert resp.status_code == 415
