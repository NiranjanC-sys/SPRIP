"""Typed application settings, loaded from the environment.

plan.md §15 requires that secrets live in the environment or a secret store and never
in the repository. That rule is only as good as the code that reads them, so this module
is the single place any secret enters the process, and it applies three protections:

**Secrets are typed as** :class:`~pydantic.SecretStr`. A ``SecretStr`` renders as
``**********`` in ``repr()``, in ``str()``, in ``model_dump()`` and therefore in every
structured log line, traceback frame and error envelope that happens to carry a settings
object. Reading the real value requires calling ``.get_secret_value()``, which is easy to
grep for in review and impossible to do by accident.

**Production refuses to start on a development default.** A placeholder secret key is
useful locally and catastrophic in production, and the failure is silent - the service
comes up, signs sessions with a value that is in the public repository, and nothing looks
wrong. :meth:`Settings._enforce_production_invariants` turns that into a startup crash.

**There is no ``.env`` fallback in production.** The file is read when it exists because
local development needs it, but ``APP_ENV=production`` additionally requires that every
secret be present in the real environment, so a stray ``.env`` copied onto a server cannot
quietly supply credentials.

The settings object is cached (:func:`get_settings`) so that the environment is read once
per process. Tests override it through the cache, not by mutating ``os.environ`` - see
:func:`reset_settings_cache`.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import quote

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "ci", "staging", "production"]

#: Environments that are handling real customer data and therefore get no leniency.
HARDENED_ENVIRONMENTS: frozenset[str] = frozenset({"staging", "production"})

#: Values that exist so that a developer can clone the repository and run it. Any of them
#: appearing in a hardened environment is a deployment error, not a preference.
_DEV_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "change-me",
        "changeme",
        "secret",
        "password",
        "postgres",
        "minioadmin",
        "dev-only-not-a-real-secret",
        "",
    }
)

#: Minimum length for a signing key. 32 bytes of entropy is the floor for HMAC-SHA256;
#: shorter keys are accepted by every library and weaken the construction silently.
MIN_SECRET_LENGTH = 32

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _DEV_PLACEHOLDERS


#: The dotenv files every settings group reads, in increasing precedence.
#:
#: Listed once and shared, because each nested group below is instantiated *independently*
#: by its ``default_factory`` - it does not inherit anything from :class:`Settings`. A group
#: whose ``model_config`` omits ``env_file`` therefore reads only real environment
#: variables and silently ignores ``.env``, which produces the worst possible failure shape:
#: ``APP_ENV`` and ``DEBUG`` are picked up from the file, so the file is evidently being
#: read, while ``DB_HOST`` quietly stays ``localhost`` and the developer spends an afternoon
#: on a connection timeout to a database they never configured.
ENV_FILES: tuple[str, ...] = (".env", ".env.local")


def _group_config(prefix: str) -> SettingsConfigDict:
    """Config for one nested settings group.

    ``extra="ignore"`` is required rather than stylistic: every group reads the same
    ``.env`` file, so ``AuthSettings`` sees ``DB_HOST`` and every other unrelated key in it.
    """
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class _GroupSettings(BaseSettings):
    """Base for the nested groups, so none of them can be defined without ``env_file``."""

    model_config = _group_config("")


class DatabaseSettings(_GroupSettings):
    """PostgreSQL connection and pool configuration.

    Two roles, deliberately. The application connects as a role that is *subject to*
    row-level security, so a missing ``app.tenant_id`` yields zero rows rather than every
    tenant's rows. Migrations connect as an owner role that bypasses RLS, because a policy
    cannot be created by a role the policy applies to. Collapsing them into one superuser
    connection string is the single most common way a multi-tenant product loses its
    isolation guarantee, and it cannot be detected by any test that only ever runs as that
    one role - which is why :mod:`tests.security.test_rls` asserts the application role is
    *not* a superuser and *not* the table owner.
    """

    model_config = _group_config("DB_")

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65_535)
    name: str = "speaker_roi"
    user: str = "speaker_roi_app"
    password: SecretStr = SecretStr("dev-only-not-a-real-secret")

    #: Owner role used only by Alembic. Left unset in the application containers so that
    #: an API process physically cannot connect with RLS-bypassing credentials.
    migration_user: str | None = None
    migration_password: SecretStr | None = None

    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=5, ge=0, le=100)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)
    pool_recycle_seconds: int = Field(default=1_800, gt=0)

    #: Statement timeout applied to every application session. A runaway analytical query
    #: holding a connection is how the API stops answering; the analytical work belongs in
    #: the worker, where the timeout is far higher.
    statement_timeout_ms: int = Field(default=15_000, gt=0)
    lock_timeout_ms: int = Field(default=5_000, gt=0)

    echo_sql: bool = False

    @field_validator("name", "user", "migration_user")
    @classmethod
    def _validate_identifier(cls, value: str | None) -> str | None:
        """Reject anything that is not a bare SQL identifier.

        The database and role names reach ``SET ROLE`` and ``search_path`` statements,
        which cannot be parameterised. Validating the shape here means the interpolation
        sites downstream are provably safe rather than merely reviewed.
        """
        if value is None:
            return None
        if not _SAFE_IDENTIFIER.match(value):
            raise ValueError(
                f"{value!r} is not a valid PostgreSQL identifier; only letters, digits and "
                "underscores are accepted, and it may not start with a digit"
            )
        return value

    def dsn(self, *, driver: str = "postgresql+asyncpg", migration: bool = False) -> str:
        """Assemble a SQLAlchemy URL.

        The password is percent-encoded, because a generated password containing ``@`` or
        ``/`` otherwise produces a URL that parses into a different host.
        """
        if migration:
            user = self.migration_user or self.user
            secret = self.migration_password or self.password
        else:
            user = self.user
            secret = self.password
        password = quote(secret.get_secret_value(), safe="")
        return f"{driver}://{quote(user, safe='')}:{password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_dsn(self) -> str:
        """Synchronous URL for Alembic, which does not run in an event loop."""
        return self.dsn(driver="postgresql+psycopg", migration=True)


class RedisSettings(_GroupSettings):
    """Broker, result backend and cache.

    Three logical databases on one server rather than one shared database. Celery's
    result backend and the application cache have different eviction requirements - the
    cache is disposable, a task result is not - and ``FLUSHDB`` on a shared database
    during a cache clear would discard in-flight job results.
    """

    model_config = _group_config("REDIS_")

    #: Whether a Redis server exists at all.
    #:
    #: Distinguishes "not configured" from "configured but unreachable", which the rate
    #: limiter must be able to tell apart. Unreachable is a warning and a fail-open; absent is
    #: a supported single-process development mode with in-process limits. Without this flag
    #: the two are indistinguishable, and a developer with no Redis pays a connect timeout on
    #: every request while a production Redis outage looks like a normal local setup.
    enabled: bool = True

    host: str = "localhost"
    port: int = Field(default=6379, ge=1, le=65_535)
    password: SecretStr | None = None
    broker_db: int = Field(default=0, ge=0, le=15)
    result_db: int = Field(default=1, ge=0, le=15)
    cache_db: int = Field(default=2, ge=0, le=15)
    use_tls: bool = False

    def url(self, db: int) -> str:
        scheme = "rediss" if self.use_tls else "redis"
        auth = f":{quote(self.password.get_secret_value(), safe='')}@" if self.password else ""
        return f"{scheme}://{auth}{self.host}:{self.port}/{db}"

    @property
    def broker_url(self) -> str:
        return self.url(self.broker_db)

    @property
    def result_url(self) -> str:
        return self.url(self.result_db)

    @property
    def cache_url(self) -> str:
        return self.url(self.cache_db)


class StorageSettings(_GroupSettings):
    """Object storage for uploads, exports and model artefacts.

    plan.md §15 requires private buckets and short-lived authorized download URLs, so
    ``presign_ttl_seconds`` is capped rather than merely defaulted: a fifteen-minute link
    that leaks into a chat log expires; a seven-day link is a credential.
    """

    model_config = _group_config("STORAGE_")

    endpoint_url: str | None = "http://localhost:9000"
    region: str = "us-east-1"
    access_key: SecretStr = SecretStr("minioadmin")
    secret_key: SecretStr = SecretStr("minioadmin")

    upload_bucket: str = "speaker-roi-uploads"
    export_bucket: str = "speaker-roi-exports"
    artifact_bucket: str = "speaker-roi-artifacts"

    #: MinIO needs path style; real S3 prefers virtual-hosted style.
    use_path_style: bool = True
    server_side_encryption: str | None = None

    presign_ttl_seconds: int = Field(default=900, ge=60, le=3_600)
    max_upload_bytes: int = Field(default=200 * 1024 * 1024, gt=0)
    multipart_threshold_bytes: int = Field(default=16 * 1024 * 1024, gt=0)

    @property
    def buckets(self) -> tuple[str, ...]:
        return (self.upload_bucket, self.export_bucket, self.artifact_bucket)


class AuthSettings(_GroupSettings):
    """Session, token and password policy.

    Opaque server-side sessions rather than stateless JWT access tokens for the browser.
    A revoked JWT is valid until it expires, and plan.md §15 requires forced re-auth for
    sensitive operations plus immediate effect for a role change - neither of which a
    self-contained token can deliver. JWTs are still issued for machine-to-machine
    integrations, where revocation is handled by rotating the client secret.
    """

    model_config = _group_config("AUTH_")

    secret_key: SecretStr = SecretStr("dev-only-not-a-real-secret-change-me-now")
    session_cookie_name: str = "sr_session"
    session_ttl_seconds: int = Field(default=12 * 3_600, ge=300)
    session_idle_timeout_seconds: int = Field(default=60 * 60, ge=300)
    cookie_secure: bool = True
    cookie_domain: str | None = None
    #: ``lax`` and not ``none``: the SPA is served same-site, and ``none`` would permit
    #: the session cookie to ride along on a cross-site request.
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    #: Argon2id parameters. 64 MiB and three passes is the OWASP 2024 recommendation;
    #: lowering them is a security decision, so they are configuration and not constants.
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_cost_kib: int = Field(default=65_536, ge=8_192)
    argon2_parallelism: int = Field(default=4, ge=1)

    password_min_length: int = Field(default=12, ge=8)
    max_failed_logins: int = Field(default=5, ge=1)
    lockout_seconds: int = Field(default=900, ge=60)

    #: Operations that re-prompt for credentials even inside a live session: publishing a
    #: result, approving a finance assumption, changing a role.
    reauth_window_seconds: int = Field(default=300, ge=60)

    mfa_issuer: str = "Speaker ROI"
    mfa_required_for_roles: tuple[str, ...] = ()

    invitation_ttl_hours: int = Field(default=72, ge=1)

    oidc_enabled: bool = False
    oidc_issuer: AnyHttpUrl | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: tuple[str, ...] = ("openid", "email", "profile")

    @model_validator(mode="after")
    def _oidc_is_all_or_nothing(self) -> Self:
        if self.oidc_enabled and not (
            self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret
        ):
            raise ValueError(
                "AUTH_OIDC_ENABLED is set but issuer, client id or client secret is missing; "
                "a half-configured identity provider fails at the redirect, after the user "
                "has already left the application"
            )
        return self

    @model_validator(mode="after")
    def _idle_timeout_within_absolute(self) -> Self:
        if self.session_idle_timeout_seconds > self.session_ttl_seconds:
            raise ValueError(
                "session idle timeout exceeds the absolute session lifetime, which makes it "
                "dead configuration: the absolute limit always fires first"
            )
        return self


class AISettings(_GroupSettings):
    """Governed narration.

    plan.md §14 forbids text-to-SQL. The model receives a structured fact payload
    assembled by allowlisted read-only semantic functions and narrates it; it never sees
    a schema, never emits a query and cannot widen its own scope. ``enabled=False`` is a
    supported production configuration, not a degraded one - :mod:`speaker_roi_api` falls
    back to deterministic templated narration built from the same fact payload, so the
    numbers on screen are identical and only the prose is plainer.
    """

    model_config = _group_config("AI_")

    enabled: bool = False
    provider: Literal["anthropic", "azure_openai", "none"] = "none"
    api_key: SecretStr | None = None
    base_url: str | None = None
    model: str = "claude-sonnet-4-5"
    max_output_tokens: int = Field(default=1_500, ge=128, le=16_000)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    request_timeout_seconds: float = Field(default=45.0, gt=0)

    #: Per-tenant daily ceiling. An unbounded natural-language surface is an unbounded
    #: invoice, and the failure mode is a loop in an integration rather than a user.
    daily_request_quota: int = Field(default=500, ge=0)
    max_prompt_chars: int = Field(default=8_000, ge=500)

    @model_validator(mode="after")
    def _credentials_present_when_enabled(self) -> Self:
        if self.enabled and self.provider != "none" and self.api_key is None:
            raise ValueError(
                "AI_ENABLED is true but AI_API_KEY is unset; set AI_ENABLED=false to use "
                "deterministic narration instead of failing at the first request"
            )
        return self


class ObservabilitySettings(_GroupSettings):
    """Logging, metrics and tracing.

    ``log_format`` defaults to JSON because these logs are read by a collector, not a
    person, and a console renderer that pretty-prints a dict is how a redacted field gets
    re-introduced. Local development sets ``console``.
    """

    model_config = _group_config("OBS_")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    #: Emitting SQL at DEBUG prints bound parameters, which are patient-adjacent data.
    #: plan.md §15: never log file contents or sensitive free text.
    log_sql_parameters: bool = False

    metrics_enabled: bool = True
    metrics_path: str = "/metrics"

    tracing_enabled: bool = False
    otlp_endpoint: str | None = None
    trace_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)

    sentry_dsn: SecretStr | None = None


class AnalyticsSettings(_GroupSettings):
    """Defaults for the causal engine and the forecasting models.

    These are *defaults for new analysis specifications*, not live tuning knobs. An
    analysis run persists the specification it used, and a published result is reproducible
    from that stored specification rather than from whatever the environment says today -
    otherwise changing an environment variable silently changes the meaning of a number a
    commercial team has already acted on.
    """

    model_config = _group_config("ANALYTICS_")

    default_pre_window_months: int = Field(default=12, ge=6)
    default_post_window_months: int = Field(default=3, ge=1)
    default_caliper_sd: float = Field(default=0.5, gt=0)
    default_control_ratio: int = Field(default=3, ge=1)
    bootstrap_iterations: int = Field(default=500, ge=100)
    #: A full sensitivity suite is nine to eleven pipeline runs, so an analysis is always
    #: a job. This is the worker's ceiling, not the API's.
    analysis_timeout_seconds: int = Field(default=3_600, ge=60)
    max_concurrent_analyses_per_tenant: int = Field(default=2, ge=1)


class Settings(BaseSettings):
    """Root settings object.

    Nested groups are instantiated with their own prefixes rather than nested delimiters,
    so an operator sets ``DB_HOST`` and ``AUTH_SECRET_KEY`` - flat, greppable names that
    match what a Kubernetes secret or a systemd unit actually contains.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    app_env: Environment = "local"
    app_name: str = "speaker-roi"
    version: str = "1.0.0"
    debug: bool = False

    api_prefix: str = "/api/v1"
    #: Explicit list, never ``*``. Credentialed CORS with a wildcard origin is rejected by
    #: browsers anyway, and a permissive default is how it reaches production.
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")

    #: Fixed page size ceiling. Cursor pagination everywhere (plan.md §13): keyset paging
    #: is stable under concurrent inserts, and ``OFFSET`` on a large analytical table is a
    #: sequential scan the tenant pays for.
    default_page_size: int = Field(default=50, ge=1, le=200)
    max_page_size: int = Field(default=200, ge=1, le=1_000)

    request_timeout_seconds: float = Field(default=30.0, gt=0)
    max_request_bytes: int = Field(default=2 * 1024 * 1024, gt=0)

    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = Field(default=300, ge=1)
    #: Login and password reset get their own much lower budget; the general limit is far
    #: too generous to slow a credential-stuffing run.
    auth_rate_limit_per_minute: int = Field(default=10, ge=1)

    #: Retention of the raw uploaded file. plan.md §15 wants the smallest durable footprint
    #: consistent with being able to explain a published number.
    upload_retention_days: int = Field(default=90, ge=1)
    audit_retention_days: int = Field(default=2_557, ge=365)  # seven years

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    ai: AISettings = Field(default_factory=AISettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Accept ``a,b,c`` as well as a JSON array.

        Environment variables are strings. Pydantic parses ``["a","b"]`` but an operator
        writing a comma-separated list is the overwhelmingly common case, and failing on
        it produces a startup error that reads like a bug in the application.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value
            return tuple(part.strip() for part in stripped.split(",") if part.strip())
        return value

    @field_validator("max_page_size")
    @classmethod
    def _max_page_size_above_default(cls, value: int, info: ValidationInfo) -> int:
        default = info.data.get("default_page_size", 50)
        if value < default:
            raise ValueError(
                f"max_page_size ({value}) is below default_page_size ({default}), so the "
                "default page can never be served"
            )
        return value

    @model_validator(mode="after")
    def _enforce_production_invariants(self) -> Self:
        """Refuse to start in a hardened environment on development defaults.

        Each check here corresponds to a real incident class. Failing at startup is the
        only reliable moment to catch them: after startup the service looks healthy, and
        the defect surfaces as a breach rather than as an error.
        """
        if self.app_env not in HARDENED_ENVIRONMENTS:
            return self

        problems: list[str] = []

        secret = self.auth.secret_key.get_secret_value()
        if _is_placeholder(secret) or "change" in secret.lower():
            problems.append("AUTH_SECRET_KEY is still a development placeholder")
        if len(secret) < MIN_SECRET_LENGTH:
            problems.append(
                f"AUTH_SECRET_KEY is {len(secret)} characters; at least {MIN_SECRET_LENGTH} "
                "are required for HMAC-SHA256 session signing"
            )
        if _is_placeholder(self.database.password.get_secret_value()):
            problems.append("DB_PASSWORD is still a development placeholder")
        if _is_placeholder(self.storage.secret_key.get_secret_value()):
            problems.append("STORAGE_SECRET_KEY is still a development placeholder")

        if self.debug:
            problems.append("DEBUG is true, which serves tracebacks to clients")
        if not self.auth.cookie_secure:
            problems.append(
                "AUTH_COOKIE_SECURE is false, which permits the session cookie "
                "to travel over plaintext HTTP"
            )
        if self.auth.cookie_samesite == "none":
            problems.append(
                "AUTH_COOKIE_SAMESITE=none allows the session cookie to be sent "
                "on cross-site requests"
            )
        if "*" in self.cors_origins:
            problems.append(
                "CORS_ORIGINS contains '*', which cannot be combined with "
                "credentialed requests and is never the intent"
            )
        if not self.rate_limit_enabled:
            problems.append(
                "RATE_LIMIT_ENABLED is false, leaving the login endpoint open "
                "to credential stuffing"
            )
        if self.observability.log_sql_parameters:
            problems.append(
                "OBS_LOG_SQL_PARAMETERS is true, which writes bound parameters - "
                "including patient-adjacent values - to the log stream"
            )
        if self.database.migration_user and self.database.migration_user == self.database.user:
            problems.append(
                "DB_MIGRATION_USER equals DB_USER, so the application connects "
                "with a role that owns its tables and bypasses row-level security"
            )

        if problems:
            listed = "\n".join(f"  - {p}" for p in problems)
            raise ValueError(
                f"refusing to start with APP_ENV={self.app_env!r}:\n{listed}\n"
                "Each of these is safe locally and unsafe with real data. Set them in the "
                "environment or the secret store; see docs/runbook.md."
            )
        return self

    @property
    def is_hardened(self) -> bool:
        return self.app_env in HARDENED_ENVIRONMENTS

    @property
    def is_testing(self) -> bool:
        return self.app_env in {"test", "ci"}

    def safe_dump(self) -> dict[str, Any]:
        """A settings snapshot suitable for a startup log line or a health payload.

        ``SecretStr`` already masks itself, but this goes further and drops the keys
        entirely. A masked key still tells a reader which secrets exist and how long they
        are, and the startup banner has no need for either.
        """
        raw = self.model_dump(mode="json")

        def strip(node: Any) -> Any:
            if isinstance(node, dict):
                return {
                    k: strip(v)
                    for k, v in node.items()
                    if not any(token in k for token in ("password", "secret", "key", "dsn", "url"))
                    or k in {"endpoint_url", "base_url", "otlp_endpoint"}
                }
            if isinstance(node, list):
                return [strip(v) for v in node]
            return node

        return strip(raw)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read from the environment once.

    Cached deliberately: constructing ``Settings`` re-reads ``.env`` and re-runs every
    validator, and it is called from request scope. FastAPI overrides it in tests through
    the dependency system; non-web tests call :func:`reset_settings_cache`.
    """
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings so the next call re-reads the environment.

    For tests that need to prove a validator fires - for example that
    ``APP_ENV=production`` with a placeholder secret refuses to start. Production code has
    no reason to call this.
    """
    get_settings.cache_clear()


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward for the directory holding ``pyproject.toml``.

    Used by the CLI and by Alembic to resolve paths independently of the working
    directory, so that ``speaker-roi db upgrade`` behaves the same from the repository
    root and from a container whose entrypoint is elsewhere.
    """
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(
        "could not locate pyproject.toml above "
        f"{current}; pass an explicit path or run from inside the repository"
    )


__all__ = [
    "ENV_FILES",
    "HARDENED_ENVIRONMENTS",
    "MIN_SECRET_LENGTH",
    "AISettings",
    "AnalyticsSettings",
    "AuthSettings",
    "DatabaseSettings",
    "Environment",
    "ObservabilitySettings",
    "RedisSettings",
    "Settings",
    "StorageSettings",
    "find_repo_root",
    "get_settings",
    "reset_settings_cache",
]
