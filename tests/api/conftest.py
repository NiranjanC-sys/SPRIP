"""Fixtures for HTTP-level integration tests against the running dev server.

These tests require:
  - API server running on http://localhost:8000
  - Database seeded with demo data (scripts/seed_demo_data.py, scripts/seed_analytics.py)

Tests skip when the server is unreachable.
"""
from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("TEST_API_URL", "http://localhost:8000")
API = f"{BASE_URL}/api/v1"

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@demo.com")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "TestAdmin1!")


def _server_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/api/v1/auth/login", timeout=3)
        return r.status_code in (200, 401, 405, 422)
    except httpx.ConnectError:
        return False


skip_no_server = pytest.mark.skipif(
    not _server_reachable(), reason="API server not reachable"
)


@pytest.fixture(scope="session")
def auth_cookies() -> dict[str, str]:
    """Login as admin and return session cookies."""
    r = httpx.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text[:200]}")
    return dict(r.cookies)


@pytest.fixture(scope="session")
def client(auth_cookies: dict[str, str]) -> httpx.Client:
    """Authenticated httpx client."""
    c = httpx.Client(base_url=API, cookies=auth_cookies, timeout=15)
    yield c
    c.close()
