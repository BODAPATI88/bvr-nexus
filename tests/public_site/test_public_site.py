"""
Tests for the Public Site FastAPI service.
No external calls are made — the service is self-contained.
"""
import sys
import importlib.util
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
_SITE_DIR = _REPO_ROOT / "public-site"

sys.path.insert(0, str(_SITE_DIR))

_spec = importlib.util.spec_from_file_location("public_main", str(_SITE_DIR / "main.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

app = _mod.app


class TestHealthEndpoint:
    async def test_health_returns_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.status_code == 200

    async def test_health_status_ok(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["status"] == "ok"

    async def test_health_service_name(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["service"] == "public-site"

    async def test_health_contains_version(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert "version" in r.json()


class TestIndexPage:
    async def test_index_returns_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/")
        assert r.status_code == 200

    async def test_index_contains_bvr_nexus(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/")
        assert b"BVR Nexus" in r.content

    async def test_index_contains_enterprise_keywords(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/")
        assert b"enterprise" in r.content.lower() or b"Enterprise" in r.content

    async def test_index_contains_executive_login_link(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/")
        assert b"Executive" in r.content or b"ceo" in r.content.lower()

    async def test_index_contains_seven_layers(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/")
        assert b"L0" in r.content and b"L6" in r.content

    async def test_index_navigation_links(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/")
        assert b"/products" in r.content
        assert b"/support" in r.content


class TestProductsPage:
    async def test_products_returns_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/products")
        assert r.status_code == 200

    async def test_products_contains_heading(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/products")
        assert b"Products" in r.content

    async def test_products_lists_api_gateway(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/products")
        assert b"API Gateway" in r.content

    async def test_products_lists_ai_gateway(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/products")
        assert b"AI Gateway" in r.content

    async def test_products_lists_sdk(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/products")
        assert b"SDK" in r.content

    async def test_products_shows_version(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/products")
        assert b"2.0.0" in r.content


class TestSupportPage:
    async def test_support_returns_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/support")
        assert r.status_code == 200

    async def test_support_contains_heading(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/support")
        assert b"Support" in r.content

    async def test_support_contains_faq(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/support")
        assert b"FAQ" in r.content or b"Frequently" in r.content

    async def test_support_mentions_vault(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/support")
        assert b"Vault" in r.content


class TestLoginRedirect:
    async def test_login_redirects(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as c:
            r = await c.get("/login")
        assert r.status_code == 302

    async def test_login_redirect_target_is_ceo_url(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as c:
            r = await c.get("/login")
        assert "ceo" in r.headers.get("location", "").lower() or r.status_code == 302
