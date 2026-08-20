"""The ASGI application factory.

A factory rather than a module-level ``app = FastAPI()``, because the tests need an application
built against test settings and a fresh metrics registry, and a module-level instance is
constructed at import time - before a fixture can change anything.

**Middleware order is the part to read carefully.** Starlette applies middleware in reverse
registration order, so the *last* one added is the outermost. Reading outward-in, the intended
order is:

1. ``SecurityHeadersMiddleware`` - outermost, so its headers are on *every* response, including
   the 413 from the body limiter and the 500 from a middleware that itself failed.
2. ``BodySizeLimitMiddleware`` - before anything reads the body, so an oversized upload is
   refused without being buffered.
3. ``CORSMiddleware`` - must see the preflight before authentication does, or a browser gets an
   opaque failure on ``OPTIONS`` instead of a CORS error it can report.
4. ``RequestContextMiddleware`` - binds the correlation id and tenant context.
5. ``ObservabilityMiddleware`` - innermost of the four, so the duration it measures is the
   handler's, not the stack's, and so the context is already bound when it logs.

**The lifespan refuses to start on two conditions**, both of which are silent in every
functional test and catastrophic in production: a connected role that bypasses row-level
security, and a database schema that does not match the code. The second check exists because
a rolling deploy that reaches a replica before its migration presents as a 500 at a missing
column, three layers deep, minutes after the deploy looked successful.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from speaker_roi_api import handlers
from speaker_roi_api.middleware.context import (
    CORRELATION_HEADER,
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
)
from speaker_roi_api.middleware.observability import ObservabilityMiddleware
from speaker_roi_api.middleware.rate_limit import close_limiter, get_limiter
from speaker_roi_api.middleware.security import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from speaker_roi_api.openapi import DESCRIPTION, TAGS, customise_openapi
from speaker_roi_api.routers import all_routers
from speaker_roi_api.routers.health import metrics_router
from speaker_roi_api.routers.health import router as health_router
from speaker_roi_core.config import Settings, get_settings
from speaker_roi_core.db.session import (
    assert_rls_enforced,
    dispose_engine,
    get_engine,
    probe_rls,
)
from speaker_roi_core.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

log = get_logger(__name__)

#: Resolved at import time rather than inside the startup coroutine. A blocking stat call on the
#: event loop is a small sin here and a habit worth not forming, and the answer cannot change
#: while the process runs: either this build shipped the migration directory or it did not.
_MIGRATIONS_PACKAGED = (Path(__file__).resolve().parents[4] / "migrations" / "versions").is_dir()


async def _check_schema_version() -> None:
    """Compare the database's Alembic revision against the one this build expects.

    A mismatch is a hard refusal in a hardened environment and a loud warning elsewhere. The
    asymmetry is deliberate: a developer mid-migration wants to keep working, and a production
    replica running against a schema it was not built for will corrupt data or 500 - and it is
    far better to fail to start, which the orchestrator reports, than to start and serve.

    ``alembic_version`` is readable by the application role on purpose. The migration revokes
    ``PUBLIC`` on the schema and then re-grants ``SELECT`` on this one table, precisely so this
    check is possible without the application holding DDL privileges.
    """
    from sqlalchemy import text

    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM public.alembic_version"))
        applied = {row[0] for row in result}

    if not _MIGRATIONS_PACKAGED:
        log.info("api.schema_version.unknown", detail="migration directory not packaged")
        return

    if not applied:
        raise RuntimeError(
            "the database has no Alembic revision recorded. Run 'alembic upgrade head' "
            "before starting the API; see docs/runbook.md."
        )
    log.info("api.schema_version", applied=sorted(applied))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down, in the order the dependencies demand."""
    settings: Settings = app.state.settings
    configure_logging(
        level=settings.observability.log_level,
        fmt=settings.observability.log_format,
        service=settings.app_name,
        version=settings.version,
        environment=settings.app_env,
    )
    log.info(
        "api.starting",
        environment=settings.app_env,
        version=settings.version,
        hardened=settings.is_hardened,
    )

    if settings.is_hardened:
        # Behavioural, not declarative. Asking the catalogue whether a policy exists is a
        # weaker claim than trying a cross-tenant read and being refused - and the difference
        # is exactly the misconfiguration that matters, an application role that owns its
        # tables and therefore is not subject to its own policies.
        await assert_rls_enforced()
        await _check_schema_version()
    else:
        try:
            report = await probe_rls()
            log.info("api.rls_probe", **{k: v for k, v in report.items() if k != "detail"})
        except Exception as exc:
            # Not fatal locally. A developer who has not yet run migrations should get a
            # readable warning and a working server, not a startup crash whose message is
            # about row-level security.
            log.warning(
                "api.rls_probe_failed",
                error=type(exc).__name__,
                remediation="run 'speaker-roi db upgrade'; see docs/runbook.md#rls-verification",
            )

    if settings.rate_limit_enabled:
        # Constructed eagerly so a missing Redis is one warning at boot rather than one per
        # request, and so the "limits are per-process" notice appears in the startup log
        # where an operator will see it.
        get_limiter()

    try:
        yield
    finally:
        log.info("api.stopping")
        await close_limiter()
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. The only public entry point in this module."""
    settings = settings or get_settings()

    app = FastAPI(
        title="Speaker Programme ROI Intelligence",
        description=DESCRIPTION,
        version=settings.version,
        openapi_tags=TAGS,
        lifespan=lifespan,
        default_response_class=handlers.ORJSONResponse,
        # Interactive docs off in a hardened environment. They are a convenience, and an
        # accurate map of every endpoint and payload shape is a convenience for an attacker
        # too; the schema is published to consumers through the generated client instead.
        docs_url=None if settings.is_hardened else "/docs",
        redoc_url=None if settings.is_hardened else "/redoc",
        openapi_url=None if settings.is_hardened else "/openapi.json",
    )
    app.state.settings = settings

    handlers.install(app)
    _install_middleware(app, settings)
    _install_routes(app, settings)
    customise_openapi(app, settings)
    return app


def _install_middleware(app: FastAPI, settings: Settings) -> None:
    """Add the stack. Registration order is *reverse* of execution order - see the module docstring."""
    # Innermost first.
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(
        RequestContextMiddleware,
        # Only believed when a proxy we operate is known to overwrite the header. Trusting it
        # unconditionally makes every rate limit and every lockout bypassable by setting a
        # header, which is the most common way a correct limiter is rendered useless.
        trust_forwarded_for=settings.is_hardened,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            # Credentialed, because the session is a cookie. This is why a wildcard origin is
            # rejected in the settings validator rather than merely discouraged: the two are
            # mutually exclusive in the fetch specification, and a browser silently drops the
            # credentials rather than reporting the conflict.
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                CORRELATION_HEADER,
                "X-Requested-With",
            ],
            expose_headers=[CORRELATION_HEADER, REQUEST_ID_HEADER, "Retry-After", "Location"],
            max_age=600,
        )

    app.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=settings.max_request_bytes,
        upload_max_body_bytes=settings.storage.max_upload_bytes,
        upload_path_prefixes=(f"{settings.api_prefix}/uploads",),
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        # HSTS only where TLS is genuinely terminated in front of us. Sent from a local HTTP
        # server it would pin the developer's browser to https://localhost for two years,
        # which is unrecoverable without clearing browser-internal state.
        hsts=settings.is_hardened,
    )
    if settings.trusted_hosts and settings.is_hardened:
        # Host-header validation. Without it, a request with a forged Host reaches the
        # application and any absolute URL it generates - a password-reset link, most
        # damagingly - points at the attacker's domain.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))


def _install_routes(app: FastAPI, settings: Settings) -> None:
    app.include_router(health_router)
    if settings.observability.metrics_enabled:
        app.include_router(metrics_router(settings.observability.metrics_path))
    for router in all_routers():
        app.include_router(router, prefix=settings.api_prefix)


def routes_summary(app: FastAPI) -> Sequence[str]:
    """Every mounted route, for the ``speaker-roi api routes`` command and for tests.

    A test asserts against this so that adding an endpoint without a permission guard is a
    test failure rather than a discovery. That test is the reason this function exists at all.

    ``app.routes`` is not a flat list. An ``include_router`` call leaves a lazy wrapper in place
    rather than copying each route up, so walking the list naively finds four documentation
    endpoints and none of the API - which would make the guard test pass by finding nothing to
    check. The wrappers expose their resolved children through ``effective_candidates()``, and
    those carry the fully prefixed path, so this recurses through them.
    """
    summary: set[str] = set()

    def walk(routes: Iterable[object]) -> None:
        for route in routes:
            candidates = getattr(route, "effective_candidates", None)
            if callable(candidates):
                walk(candidates())
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path and methods:
                for method in methods:
                    if method not in {"HEAD", "OPTIONS"}:
                        summary.add(f"{method} {path}")

    walk(app.routes)
    return sorted(summary)


#: The instance uvicorn imports: ``uvicorn speaker_roi_api.main:app``. Built at import time,
#: which is correct for the process entry point and is exactly what the factory exists to let
#: the tests avoid.
app = create_app()


__all__ = ["app", "create_app", "lifespan", "routes_summary"]
