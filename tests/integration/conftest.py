"""Fixtures for tests that drive the API over HTTP against a real PostgreSQL.

These catch what neither a unit test nor a database test can: that the dependency graph resolves
in the right order, that the tenant guard runs before the handler rather than beside it, that a
cursor survives a round-trip through base64 and back into a ``timestamptz`` comparison, and that
row-level security is still isolating tenants when the connection comes from the application's own
pool instead of from a fixture.

ASGI transport rather than a live server: no socket, no port to collide with, no start-up race -
and the middleware stack, the exception handlers and the dependency graph are exactly the ones a
deployed replica would use, because it is the same application object.

The tenant is provisioned by the same ``admin bootstrap`` code path an operator runs, not by
planting rows. That is the correct coupling: a setup procedure nobody exercises is a setup
procedure that does not work, and these tests are the only thing standing between "the CLI ran
without error" and "the account it created can actually do something".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from tests.conftest import DEFAULT_HOST, DEFAULT_PORT, ROLE_PASSWORDS, TEST_DB, url_for

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient

#: Passwords for the fixture accounts. Long enough for the policy, and not secret in any
#: meaningful sense - they exist only inside a disposable test database.
DEMO_PASSWORD = "fixture-passphrase-demo-42"
RIVAL_PASSWORD = "fixture-passphrase-rival-42"

API = "/api/v1"


@dataclass(frozen=True, slots=True)
class Actor:
    """One provisioned tenant and the administrator who can act inside it."""

    tenant_id: uuid.UUID
    tenant_code: str
    user_id: uuid.UUID
    email: str
    password: str


@pytest_asyncio.fixture
async def api_env(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Point the process-wide settings and engine at the test database.

    The engine is installed through ``set_engine_for_tests`` because that is the documented seam,
    and the ``DB_*`` variables are set as well - not redundantly. The engine covers every query
    the application makes; the variables cover the code that *reports* the DSN rather than
    connecting with it, and leaving those pointing at ``speaker_roi`` would make the health
    endpoint describe a database these tests are not using.

    The settings cache is cleared on the way in *and* on the way out. The way out matters more
    than it looks: a cached ``Settings`` holding the test DSN would be inherited by any later test
    that reads configuration, and the symptom of that is a test which passes alone and fails in a
    suite.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from speaker_roi_core.config import reset_settings_cache
    from speaker_roi_core.db import session as session_module

    monkeypatch.setenv("DB_HOST", DEFAULT_HOST)
    monkeypatch.setenv("DB_PORT", str(DEFAULT_PORT))
    monkeypatch.setenv("DB_NAME", TEST_DB)
    monkeypatch.setenv("DB_USER", "app_rw")
    monkeypatch.setenv("DB_PASSWORD", ROLE_PASSWORDS["app_rw"])
    # Off for the duration. The limiter needs Redis and fails open without it, but a suite that
    # shares one bucket across tests makes the *last* test in a file flaky rather than the first,
    # and that is the hardest kind of flake to attribute. Rate limiting has its own tests.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    # httpx's ASGI transport uses http://, so the Secure flag must be off or the
    # cookie is never sent back.
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    # A fixed key so the encrypted TOTP secret written by one request can be decrypted by the
    # next. Without it each `Settings` construction would mint a new one and enrolment would fail
    # at the confirmation step with a decryption error rather than a wrong-code error.
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-only-key-not-used-anywhere-else-0123456789")
    reset_settings_cache()

    from speaker_roi_api.middleware.rate_limit import set_limiter_for_tests

    set_limiter_for_tests(None)

    engine = create_async_engine(
        url_for("app_rw"),
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    session_module.set_engine_for_tests(engine)
    try:
        yield
    finally:
        # Disposes *and* clears the global, so the next test that touches the database builds a
        # fresh engine from whatever settings it establishes rather than reusing this one.
        await session_module.dispose_engine()
        reset_settings_cache()


async def _provision(code: str, name: str, password: str) -> Actor:
    from speaker_roi_api.services import bootstrap as svc

    # A unique code and address per run. Bootstrap deliberately refuses to touch an existing
    # credential, so a fixed address would make the *second* run of this suite against a database
    # that was not reset produce a user whose password is not the one the test knows.
    suffix = uuid.uuid4().hex[:8]
    result = await svc.bootstrap(
        tenant_code=f"{code}-{suffix}",
        tenant_name=name,
        email=f"admin-{suffix}@{code}.example",
        display_name=f"{name} Administrator",
        password=password,
        synthetic_mode=True,
    )
    return Actor(
        tenant_id=result.tenant_id,
        tenant_code=result.tenant_code,
        user_id=result.user_id,
        email=result.user_email,
        password=password,
    )


@pytest_asyncio.fixture
async def demo(api_env: None) -> Actor:
    """A provisioned tenant with a ``PHARMA_ADMIN`` - the only role holding ``BRAND_WRITE``."""
    return await _provision("demo-pharma", "Demo Pharma India", DEMO_PASSWORD)


@pytest_asyncio.fixture
async def rival(api_env: None) -> Actor:
    """A second tenant. Its only job is to own rows that must never be visible to the first."""
    return await _provision("rival-pharma", "Rival Pharma", RIVAL_PASSWORD)


@pytest.fixture
def app(api_env: None) -> FastAPI:
    from speaker_roi_api.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        yield http


async def sign_in(client: AsyncClient, actor: Actor) -> dict[str, Any]:
    """Log in, enrol a second factor if the role demands one, and return the session payload.

    The enrolment steps live here rather than being faked in a fixture because they are part of
    what these tests assert works. ``PHARMA_ADMIN`` is in ``mfa_required_for_roles``, so a
    bootstrap-created administrator cannot reach a single permission-guarded endpoint without
    completing them - and a helper that wrote ``mfa_enrolled_at`` directly would skip exactly the
    path every operator has to walk on day one, turning a breakage there into a support ticket
    instead of a test failure.
    """
    import pyotp

    login = await client.post(
        f"{API}/auth/login", json={"email": actor.email, "password": actor.password}
    )
    assert login.status_code == 200, login.text
    payload = login.json()

    if payload["mfaRequired"]:
        assert payload["mfaEnrolmentRequired"] is True, "a fresh admin cannot already be enrolled"
        start = await client.post(f"{API}/auth/mfa/enrol")
        assert start.status_code == 200, start.text
        secret = start.json()["secret"]
        confirm = await client.post(
            f"{API}/auth/mfa/enrol/confirm", json={"code": pyotp.TOTP(secret).now()}
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["codes"], "enrolment must hand back recovery codes"
    return payload


__all__ = ["API", "DEMO_PASSWORD", "RIVAL_PASSWORD", "Actor", "sign_in"]
