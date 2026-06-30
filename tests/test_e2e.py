import requests

BASE_URL = "http://localhost:8002"

def test_health():
    r = requests.get(f"{BASE_URL}/health")
    assert r.status_code == 200

    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "bvr-api"

def test_openapi():
    r = requests.get(f"{BASE_URL}/openapi.json")
    assert r.status_code == 200

    spec = r.json()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "BVR Nexus API"
