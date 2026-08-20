"""``speaker-roi`` - the operator's command line.

This is the entry point ``pyproject.toml`` declares, and it is the only supported way to
perform a privileged operation against a deployed environment: run migrations, verify that
row-level security actually binds, provision buckets, check that configuration is
production-safe. Those things are all *possible* with a psql session and a stack of
environment variables. The reason they live here instead is that each one has a
non-obvious precondition, and a runbook step that reads "then run the SQL in §4.2" is a step
that gets performed slightly differently every time.

Three conventions hold throughout.

**Every import that is not stdlib or Typer happens inside a command.** ``speaker-roi --help``
must work in a container that has no database, no Redis and no analytics extras installed,
because the first thing anyone does with an unfamiliar CLI is ask it what it does. Deferring
the imports also means a broken optional dependency degrades one subcommand rather than
the whole tool.

**Nothing prints a secret.** Configuration is rendered through
:meth:`~speaker_roi_core.config.Settings.safe_dump`, which is the same masking the log
pipeline uses. A CLI that dumps its own config is the most common way a password reaches a
CI log, and CI logs are retained and searchable.

**Exit codes are meaningful**: 0 success, 1 a check failed (the state is wrong), 2 the
command could not run (bad arguments, missing dependency, unreachable service). A verify
script needs to distinguish "your database is misconfigured" from "I could not reach your
database", because those page different people.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

app = typer.Typer(
    name="speaker-roi",
    help="Operate the HCP Speaker Program ROI platform: schema, security, storage, services.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,  # locals hold DSNs and secrets
)

config_app = typer.Typer(
    name="config", help="Inspect and validate configuration.", no_args_is_help=True
)
db_app = typer.Typer(
    name="db", help="Schema, migrations and row-level-security checks.", no_args_is_help=True
)
storage_app = typer.Typer(
    name="storage", help="Object storage buckets and health.", no_args_is_help=True
)
models_app = typer.Typer(
    name="models", help="Train and validate the forecasting models.", no_args_is_help=True
)

app.add_typer(config_app)
app.add_typer(db_app)
app.add_typer(storage_app)
app.add_typer(models_app)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_OK = "  ok  "
_FAIL = " FAIL "
_WARN = " warn "


def _echo(status: str, label: str, detail: str = "") -> None:
    """One finding per line, status first so a column of them scans vertically."""
    colour = {_OK: typer.colors.GREEN, _FAIL: typer.colors.RED, _WARN: typer.colors.YELLOW}[status]
    typer.echo(f"[{typer.style(status, fg=colour, bold=status is not _OK)}] {label}")
    if detail:
        for line in str(detail).splitlines():
            typer.echo(f"         {line}")


def _die(message: str, code: int = 2) -> None:
    """Fail with a diagnosis rather than a traceback.

    A traceback out of a CLI tells the operator about our call stack when what they need is
    the next action. Real tracebacks still surface for genuinely unexpected errors - this is
    only for the failures we anticipated and have advice for.
    """
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _settings() -> Any:
    from speaker_roi_core.config import get_settings

    try:
        return get_settings()
    except Exception as exc:
        # Configuration failure is the single most common startup failure and its default
        # rendering is a wall of pydantic. The variable names in it are the actionable part.
        _die(f"Configuration is invalid:\n\n{exc}\n\nSee .env.example for every variable.")
        raise  # unreachable; satisfies the type checker


def _alembic_config(settings: Any) -> Any:
    """Build an Alembic config with the URL already resolved.

    ``migrations/env.py`` reads ``MIGRATION_DATABASE_URL`` or ``DATABASE_URL`` from the
    environment, so this exports the settings-derived DSN into the process environment
    rather than passing it through the Alembic config object. That keeps one resolution
    path: whether Alembic is invoked through this CLI or directly, it reads the same
    variable, and a developer debugging a migration can reproduce exactly what CI did.
    """
    from alembic.config import Config

    from speaker_roi_core.config import find_repo_root

    root = find_repo_root()
    ini = root / "alembic.ini"
    if not ini.exists():
        _die(f"No alembic.ini at {ini}. Run this from a source checkout.")
    os.environ.setdefault("MIGRATION_DATABASE_URL", settings.database.sync_dsn)
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return cfg


def _run(coro: Any) -> Any:
    """Run one coroutine and dispose the engine, whatever happened.

    Leaving the pool open holds connections until process exit, which is invisible in a
    short CLI run and very visible when a migration job with a 10-connection pool runs
    against a database already at its connection limit.
    """

    async def _wrapped() -> Any:
        from speaker_roi_core.db import dispose_engine

        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_wrapped())


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


@app.command("version")
def version_command() -> None:
    """Print the version of every component, so a bug report identifies one build."""
    from importlib.metadata import PackageNotFoundError, version

    typer.echo(f"speaker-roi            {_dist_version('speaker-roi')}")
    for label, module in (
        ("core", "speaker_roi_core"),
        ("analytics", "speaker_roi_analytics"),
        ("api", "speaker_roi_api"),
        ("worker", "speaker_roi_worker"),
    ):
        typer.echo(f"  {label:<20} {_module_state(module)}")
    for dep in ("fastapi", "sqlalchemy", "alembic", "pydantic", "pandas", "lightgbm", "celery"):
        try:
            typer.echo(f"  {dep:<20} {version(dep)}")
        except PackageNotFoundError:
            typer.echo(f"  {dep:<20} not installed")


def _dist_version(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed (running from source?)"


def _module_state(name: str) -> str:
    from importlib.util import find_spec

    try:
        return "present" if find_spec(name) else "absent"
    except (ImportError, ValueError):
        return "absent"


@app.command("doctor")
def doctor_command(
    fix: Annotated[
        bool, typer.Option("--fix", help="Create missing buckets. Never touches schema.")
    ] = False,
) -> None:
    """Check every dependency and report all findings before exiting.

    Deliberately does not stop at the first failure. An operator bringing up an environment
    wants the whole list in one pass; a tool that reports one problem per run turns a
    five-minute diagnosis into five round trips.
    """
    settings = _settings()
    failures: list[str] = []

    _echo(_OK, f"configuration loaded (env={settings.app_env}, version={settings.version})")
    if settings.is_hardened and settings.debug:
        failures.append("debug is enabled in a hardened environment")
        _echo(_FAIL, "debug mode", "debug=true with app_env=" + str(settings.app_env))

    # --- database
    try:
        state = _run(_check_db())
    except Exception as exc:
        failures.append("database unreachable")
        _echo(_FAIL, "database", f"{type(exc).__name__}: {exc}")
    else:
        _echo(_OK if state["reachable"] else _FAIL, "database", state["detail"])
        if not state["reachable"]:
            failures.append("database unreachable")
        else:
            for extension in state["missing_extensions"]:
                failures.append(f"extension {extension} missing")
                _echo(_FAIL, f"extension {extension}", "required for effective-dated constraints")
            _echo(
                _OK if state["migrations_current"] else _WARN,
                "migrations",
                f"db at {state['db_revision'] or 'none'}, head is {state['head_revision']}",
            )
            if not state["migrations_current"]:
                failures.append("migrations not at head")

    # --- redis
    try:
        detail = _run(_check_redis())
        _echo(_OK, "redis", detail)
    except Exception as exc:
        failures.append("redis unreachable")
        _echo(_FAIL, "redis", f"{type(exc).__name__}: {exc}")

    # --- storage
    try:
        report = _run(_check_storage(create=fix))
        for role, line in report.items():
            ok = line.startswith("ok")
            _echo(_OK if ok else _FAIL, f"bucket {role}", line)
            if not ok:
                failures.append(f"bucket {role} unavailable")
    except Exception as exc:
        failures.append("object storage unreachable")
        _echo(_FAIL, "object storage", f"{type(exc).__name__}: {exc}")

    typer.echo("")
    if failures:
        typer.secho(f"{len(failures)} problem(s): " + "; ".join(failures), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho("all checks passed", fg=typer.colors.GREEN, bold=True)


@app.command("serve")
def serve_command(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Development only.")] = False,
    workers: Annotated[int, typer.Option("--workers", "-w", help="Ignored with --reload.")] = 1,
) -> None:
    """Run the HTTP API.

    Binds to loopback by default. Binding to ``0.0.0.0`` is a deployment decision and
    should be made by the deployment, not inherited from a convenience default - the usual
    way an unauthenticated development service ends up reachable is a default nobody chose.
    """
    settings = _settings()
    try:
        import uvicorn
    except ImportError:
        _die("uvicorn is not installed. Install the api extra: pip install -e '.[api]'")
        return

    if reload and settings.is_hardened:
        _die(f"--reload refuses to run with app_env={settings.app_env}.")

    uvicorn.run(
        "speaker_roi_api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=1 if reload else workers,
        # The application configures structlog; uvicorn's own dictConfig would install a
        # second set of handlers and every line would appear twice, once unredacted.
        log_config=None,
        access_log=False,  # the middleware emits a richer, redacted equivalent
        proxy_headers=True,
        forwarded_allow_ips="*" if settings.is_hardened else None,
    )


@app.command("worker")
def worker_command(
    queues: Annotated[str, typer.Option("--queues", "-Q")] = "default,ingestion,analysis",
    concurrency: Annotated[int, typer.Option("--concurrency", "-c")] = 2,
    loglevel: Annotated[str, typer.Option("--loglevel", "-l")] = "info",
) -> None:
    """Run a Celery worker.

    Concurrency defaults to 2, not to the core count. An analysis run holds a database
    connection and several hundred megabytes of panel data for minutes at a time, so the
    limit that binds is memory and connections, and Celery's default of one process per core
    exhausts both on a machine that looks generously provisioned.
    """
    _settings()
    try:
        from speaker_roi_worker.app import celery_app
    except ImportError as exc:
        _die(f"the worker package is not installed ({exc}). pip install -e '.[worker]'")
        return

    celery_app.worker_main(
        [
            "worker",
            f"--queues={queues}",
            f"--concurrency={concurrency}",
            f"--loglevel={loglevel}",
            "--without-gossip",
            "--without-mingle",
        ]
    )


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(
    fmt: Annotated[str, typer.Option("--format", "-f", help="table or json.")] = "table",
) -> None:
    """Print the effective configuration with every secret masked.

    "Effective" is the point: the value that is in force after ``.env`` files, environment
    variables and defaults have been layered. Reading the three sources separately and
    composing them mentally is how an operator concludes a setting is applied when it is not.
    """
    settings = _settings()
    data = settings.safe_dump()
    if fmt == "json":
        import json

        typer.echo(json.dumps(data, indent=2, default=str, sort_keys=True))
        return

    for section, value in sorted(data.items()):
        if isinstance(value, dict):
            typer.secho(f"\n[{section}]", fg=typer.colors.CYAN, bold=True)
            for key, inner in sorted(value.items()):
                typer.echo(f"  {key:<34} {inner}")
        else:
            typer.echo(f"  {section:<36} {value}")


@config_app.command("check")
def config_check(
    environment: Annotated[
        str | None,
        typer.Option("--as", help="Validate as if APP_ENV were this, without changing it."),
    ] = None,
) -> None:
    """Validate configuration against the invariants for an environment.

    ``--as production`` is the useful form: it answers "would this deploy be rejected?"
    from a staging shell, before the deploy. The production invariants are the ones that
    cannot be tested by running the app locally, because locally they do not apply.
    """
    from speaker_roi_core.config import Settings

    if environment is None:
        settings = _settings()
        _echo(_OK, f"configuration valid for app_env={settings.app_env}")
        if not settings.is_hardened:
            typer.echo("\nRe-run with --as production to check the hardened invariants.")
        return

    try:
        probe = Settings(app_env=environment)  # type: ignore[arg-type]
    except Exception as exc:
        typer.secho(f"would be REJECTED as {environment}:\n", fg=typer.colors.RED, bold=True)
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    _echo(_OK, f"configuration would be accepted as {environment}")
    if probe.debug:
        _echo(_WARN, "debug is enabled", "hardened environments should run with debug=false")


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision.")] = "head",
    sql: Annotated[
        bool, typer.Option("--sql", help="Print the SQL instead of running it.")
    ] = False,
) -> None:
    """Apply migrations.

    ``--sql`` renders the statements for review without touching the database, which is what
    a change-controlled production deployment needs: the reviewer sees exactly what will run,
    and the same file is what runs.
    """
    from alembic import command

    settings = _settings()
    cfg = _alembic_config(settings)
    command.upgrade(cfg, revision, sql=sql)


@db_app.command("downgrade")
def db_downgrade(
    revision: Annotated[str, typer.Argument(help="Target revision, or -1 for one step back.")],
    sql: Annotated[bool, typer.Option("--sql")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Revert migrations. Destructive; confirms unless --yes.

    The confirmation exists because a downgrade drops columns, and the data in a dropped
    column is not recoverable from the migration that dropped it. In a hardened environment
    the prompt is not optional.
    """
    from alembic import command

    settings = _settings()
    if not sql and not yes:
        if settings.is_hardened:
            _die(
                f"refusing to downgrade a {settings.app_env} database non-interactively. "
                "Take a verified backup, then re-run with --yes."
            )
        typer.confirm(
            f"Downgrade {settings.database.name} at {settings.database.host} to {revision}? "
            "Column drops are not recoverable.",
            abort=True,
        )
    command.downgrade(_alembic_config(settings), revision, sql=sql)


@db_app.command("current")
def db_current(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Show the revision the database is at."""
    from alembic import command

    command.current(_alembic_config(_settings()), verbose=verbose)


@db_app.command("history")
def db_history(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Show the migration history."""
    from alembic import command

    command.history(_alembic_config(_settings()), verbose=verbose, indicate_current=True)


@db_app.command("revision")
def db_revision(
    message: Annotated[str, typer.Option("--message", "-m", help="What this migration does.")],
    autogenerate: Annotated[bool, typer.Option("--autogenerate/--empty")] = True,
) -> None:
    """Create a migration by diffing the models against the live database.

    Autogenerate is a starting point, not an answer. It does not detect a column rename (it
    emits a drop and an add, which loses the data), it does not order a backfill relative to
    a NOT NULL constraint, and ``migrations/env.py`` excludes RLS policies and partition
    children from its comparison because they are managed by hand. Read the generated file.
    """
    from alembic import command

    command.revision(_alembic_config(_settings()), message=message, autogenerate=autogenerate)
    typer.secho(
        "\nReview the generated migration before committing it: autogenerate cannot see "
        "renames, backfills, or RLS policy changes.",
        fg=typer.colors.YELLOW,
    )


@db_app.command("check-schema")
def db_check_schema() -> None:
    """Run the static schema checks that would otherwise fail mid-migration.

    No database required. Catches duplicate index names, over-long identifiers, tenant
    tables without a seekable index, and partitioned tables whose keys omit the partition
    column - each of which is valid Python that aborts an upgrade thousands of statements in.
    """
    from speaker_roi_core.config import find_repo_root

    sys.path.insert(0, str(find_repo_root() / "scripts" / "devtools"))
    try:
        import check_schema
    except ImportError as exc:
        _die(f"cannot load the schema checker ({exc}); run from a source checkout.")
        return
    raise typer.Exit(code=check_schema.main())


@db_app.command("sql")
def db_sql(
    section: Annotated[
        str,
        typer.Option("--section", "-s", help="roles, gucs, rls, grants, partitions, or all."),
    ] = "all",
) -> None:
    """Emit the security DDL that Alembic does not autogenerate.

    Roles, GUC defaults, RLS policies, grants and partition children are written by hand and
    generated from :mod:`speaker_roi_core.db.ddl`. Printing them is how a reviewer sees the
    isolation model as a single artifact rather than distributed across migration files, and
    how a DBA applies it to a database this tool cannot reach.
    """
    import speaker_roi_core.models  # noqa: F401 - registers every table
    from speaker_roi_core.db import ddl
    from speaker_roi_core.db.base import SCHEMAS, Base, declared_rls

    plan = ddl.security_plan(Base.metadata, declared_rls())
    blocks: dict[str, list[str]] = {
        "roles": ddl.create_roles_sql(),
        "gucs": ddl.guc_defaults_sql(),
        "rls": [stmt for sec in plan for stmt in ddl.enable_rls_sql(sec)],
        "grants": [*ddl.revoke_public_sql(SCHEMAS), *ddl.grants_sql(plan, SCHEMAS)],
        "partitions": [
            stmt for parent in ddl.PARTITIONED_TABLES for stmt in ddl.partition_children_sql(parent)
        ],
    }
    wanted = list(blocks) if section == "all" else [section]
    unknown = [name for name in wanted if name not in blocks]
    if unknown:
        _die(f"unknown section(s) {unknown}; choose from {', '.join(blocks)} or all")

    for name in wanted:
        typer.echo(f"\n-- ============ {name} ============")
        for statement in blocks[name]:
            typer.echo(statement.rstrip().rstrip(";") + ";")

    unprotected = ddl.unprotected_tables(plan)
    if unprotected:
        typer.secho(
            f"\n-- WARNING: {len(unprotected)} table(s) carry no RLS policy: "
            + ", ".join(unprotected),
            fg=typer.colors.RED,
        )


@db_app.command("verify-rls")
def db_verify_rls() -> None:
    """Prove that tenant isolation binds against the live database.

    This is the check that cannot be replaced by reading code. Row-level security is a
    property of the *connected role*: the policies can be correct, present and enabled, and
    still not apply, because the role the application connects as owns the table or holds
    ``BYPASSRLS``. That configuration passes every unit test and leaks every tenant.
    """
    state = _run(_verify_rls())
    ok = True
    _echo(_OK, f"connected as {state['role']}")
    for label, value, expected in (
        ("is_superuser", state["is_superuser"], False),
        ("bypasses_rls", state["bypasses_rls"], False),
        ("rls_enabled", state["rls_enabled"], True),
    ):
        good = value is expected
        ok &= good
        _echo(_OK if good else _FAIL, f"{label} = {value}", "" if good else f"expected {expected}")

    if state["unscoped_raised"]:
        _echo(_OK, "unscoped read raised", f"SQLSTATE {state['unscoped_sqlstate']}")
    else:
        ok = False
        _echo(
            _FAIL,
            "unscoped read returned rows",
            f"{state['unscoped_rows']} row(s) with no tenant bound. Either the role bypasses "
            "RLS, or the policy resolves a missing GUC to NULL instead of raising.",
        )

    if state["absent_tenant_rows"] == 0:
        _echo(_OK, "a nonexistent tenant sees no rows")
    else:
        ok = False
        _echo(
            _FAIL,
            "a nonexistent tenant sees rows",
            f"{state['absent_tenant_rows']} row(s). The policy is present but not filtering "
            "- check for a USING (true) predicate.",
        )

    typer.echo("")
    if not ok:
        typer.secho(
            "tenant isolation is NOT enforced. See docs/runbook.md#rls-verification.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=1)
    typer.secho("tenant isolation enforced", fg=typer.colors.GREEN, bold=True)


@db_app.command("wait")
def db_wait(
    timeout: Annotated[float, typer.Option("--timeout", help="Seconds to keep trying.")] = 60.0,
) -> None:
    """Block until the database accepts a query, then exit.

    For container orchestration. A dependency that is "started" is not a dependency that is
    "ready" - PostgreSQL accepts TCP connections while still replaying WAL - so a TCP probe
    lets the API start and immediately crash-loop.
    """
    import time

    settings = _settings()
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            _run(_ping())
        except Exception as exc:
            if time.monotonic() >= deadline:
                _die(
                    f"database at {settings.database.host}:{settings.database.port} not ready "
                    f"after {timeout:.0f}s ({attempt} attempts): {type(exc).__name__}: {exc}"
                )
            time.sleep(min(2.0, 0.25 * attempt))
        else:
            typer.secho(f"database ready after {attempt} attempt(s)", fg=typer.colors.GREEN)
            return


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


@storage_app.command("ensure-buckets")
def storage_ensure() -> None:
    """Create the three buckets if absent and verify none is public.

    The public-access check is the load-bearing half. An uploads bucket that is world
    readable discloses every vendor submission, and the failure is silent: uploads succeed,
    downloads succeed, and nothing in the application behaves differently.
    """
    report = _run(_check_storage(create=True))
    failed = False
    for role, line in report.items():
        ok = line.startswith("ok")
        failed |= not ok
        _echo(_OK if ok else _FAIL, f"bucket {role}", line)
    if failed:
        raise typer.Exit(code=1)


@storage_app.command("health")
def storage_health() -> None:
    """Report object storage reachability without changing anything."""
    from speaker_roi_core.storage import get_object_store

    state = _run(get_object_store().health())
    ok = bool(state.get("reachable"))
    _echo(_OK if ok else _FAIL, "object storage", str(state))
    if not ok:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


@models_app.command("train")
def models_train(
    which: Annotated[
        str, typer.Option("--model", "-m", help="attendance, impact, or all.")
    ] = "all",
    data: Annotated[Path, typer.Option("--data", "-d", help="Dataset root.")] = Path(
        "data/synthetic/full"
    ),
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("artifacts/models"),
    seed: Annotated[int, typer.Option("--seed")] = 20260819,
) -> None:
    """Fit the forecasting models and write a versioned artifact plus a validation report.

    Training refuses to write an artifact whose validation report fails its promotion gate.
    A model that ships despite a failed gate is worse than no model: the forecast still
    appears, the caveat lives in a report nobody opens, and the number reaches a slide.
    """
    try:
        from speaker_roi_analytics.training import train_models
    except ImportError as exc:
        _die(
            f"the analytics package is not available ({exc}). "
            "pip install -e '.[analytics]' from a source checkout."
        )
        return
    result = train_models(which=which, data_root=data, out_root=out, seed=seed)
    for name, report in result.items():
        _echo(_OK if report["promoted"] else _FAIL, f"model {name}", report["summary"])
    if not all(r["promoted"] for r in result.values()):
        raise typer.Exit(code=1)


@models_app.command("validate")
def models_validate(
    data: Annotated[Path, typer.Option("--data", "-d")] = Path("data/synthetic/full"),
) -> None:
    """Run the model-validation suite against a generated dataset.

    Distinct from the unit tests: these assertions need ground truth, so they run against a
    synthetic dataset whose true effects are known by construction, and they check that the
    estimator recovers them - not that the code executes.
    """
    import subprocess

    from speaker_roi_core.config import find_repo_root

    env = {**os.environ, "SYNTHETIC_DATA_ROOT": str(data)}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/model_validation", "-q"],
        cwd=find_repo_root(),
        env=env,
        check=False,
    )
    raise typer.Exit(code=completed.returncode)


# ---------------------------------------------------------------------------
# synthetic - mounted from the analytics package when it is installed
# ---------------------------------------------------------------------------


def _mount_optional_subcommands() -> None:
    """Attach the analytics and admin CLIs if their packages are importable.

    Mounted rather than reimplemented, and mounted *conditionally*, because the synthetic
    generator writes ground truth and must not be importable from a production API image.
    Reaching for it there should fail at the import, which is a clear error, rather than at
    a runtime call to a stub, which is not.

    The ``admin`` group lives in the API package because it needs the password hasher and the
    session model, and this package must not depend on that one. Inverting the dependency this
    way means a core-only image has no ``admin`` group rather than a broken one, and the
    ImportError that would otherwise surface at start-up never happens.

    Each is guarded separately: a broken analytics install must not take the admin commands with
    it, since those are what an operator reaches for when something is broken.
    """
    try:
        from speaker_roi_analytics.synthetic.cli import app as synthetic_app
    except ImportError:
        pass
    else:
        app.add_typer(synthetic_app, name="synthetic")

    try:
        from speaker_roi_api.cli import admin_app
    except ImportError:
        pass
    else:
        app.add_typer(admin_app, name="admin")


_mount_optional_subcommands()


# ---------------------------------------------------------------------------
# The async bodies. Kept separate so each command stays a thin argument parser.
# ---------------------------------------------------------------------------


async def _ping() -> None:
    from sqlalchemy import text

    from speaker_roi_core.db import get_engine

    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_db() -> dict[str, Any]:
    from sqlalchemy import text

    from speaker_roi_core.db import get_engine

    required = ("btree_gist", "pgcrypto", "pg_trgm")
    async with get_engine().connect() as conn:
        version = (await conn.execute(text("SHOW server_version"))).scalar()
        installed = {
            row[0] for row in (await conn.execute(text("SELECT extname FROM pg_extension")))
        }
        # Two statements, not one guarded statement. PostgreSQL resolves relation names
        # when it *parses*, so `SELECT ... FROM alembic_version WHERE to_regclass(...) IS
        # NOT NULL` raises UndefinedTable on a database that has never been migrated - the
        # guard runs strictly after the thing it was meant to guard.
        exists = (
            await conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
        ).scalar()
        revision = (
            (await conn.execute(text("SELECT version_num FROM public.alembic_version"))).scalar()
            if exists
            else None
        )

    head = _head_revision()
    return {
        "reachable": True,
        "detail": f"PostgreSQL {version}",
        "missing_extensions": [name for name in required if name not in installed],
        "db_revision": revision,
        "head_revision": head,
        "migrations_current": revision is not None and revision == head,
    }


def _head_revision() -> str | None:
    """The newest revision on disk, for comparison against the database."""
    from alembic.script import ScriptDirectory

    try:
        return ScriptDirectory.from_config(_alembic_config(_settings())).get_current_head()
    except Exception:
        return None


async def _check_redis() -> str:
    import redis.asyncio as aioredis

    from speaker_roi_core.config import get_settings

    cfg = get_settings().redis
    client = aioredis.Redis(
        host=cfg.host,
        port=cfg.port,
        db=cfg.cache_db,
        password=cfg.password.get_secret_value() if cfg.password else None,
        ssl=cfg.use_tls,
        socket_connect_timeout=5,
    )
    try:
        await client.ping()
        info = await client.info("server")
        return f"Redis {info.get('redis_version', '?')}"
    finally:
        await client.aclose()


async def _check_storage(*, create: bool) -> dict[str, str]:
    """Verify each bucket exists, is writable, and is not publicly readable."""
    import asyncio as _asyncio

    from botocore.exceptions import ClientError

    from speaker_roi_core.config import get_settings
    from speaker_roi_core.storage import get_object_store

    store = get_object_store()
    client = store.client
    cfg = get_settings().storage
    report: dict[str, str] = {}

    for role in ("uploads", "exports", "artifacts"):
        bucket = store.bucket_for(role)  # type: ignore[arg-type]
        try:
            await _asyncio.to_thread(client.head_bucket, Bucket=bucket)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status != 404 or not create:
                report[role] = f"unavailable: {bucket} ({status or exc})"
                continue
            try:
                kwargs: dict[str, Any] = {"Bucket": bucket}
                if cfg.region and cfg.region != "us-east-1":
                    kwargs["CreateBucketConfiguration"] = {"LocationConstraint": cfg.region}
                await _asyncio.to_thread(client.create_bucket, **kwargs)
            except ClientError as inner:
                report[role] = f"could not create {bucket}: {inner}"
                continue
            report[role] = f"ok {bucket} (created)"
        else:
            report[role] = f"ok {bucket}"

        if report[role].startswith("ok"):
            report[role] += _public_access_note(client, bucket)
    return report


def _public_access_note(client: Any, bucket: str) -> str:
    """Flag a bucket whose ACL grants a public group.

    Best effort: MinIO does not implement ``get_bucket_acl`` the way S3 does, and an
    unimplemented call is not a finding. What *is* a finding is a grant to
    ``AllUsers`` or ``AuthenticatedUsers``, and that is worth checking on every startup
    because it can be introduced from outside the application entirely.
    """
    from botocore.exceptions import ClientError

    try:
        acl = client.get_bucket_acl(Bucket=bucket)
    except ClientError:
        return ""
    public = [
        grant
        for grant in acl.get("Grants", [])
        if "AllUsers" in str(grant.get("Grantee", {}).get("URI", ""))
        or "AuthenticatedUsers" in str(grant.get("Grantee", {}).get("URI", ""))
    ]
    return " [PUBLIC ACL - every upload is world readable]" if public else ""


async def _verify_rls() -> dict[str, Any]:
    from speaker_roi_core.db import probe_rls

    # The non-raising form: this command reports every finding, so it must not abort on the
    # first one. ``assert_rls_enforced`` is the startup path and raises by design.
    return await probe_rls()


def main() -> None:
    """Console-script entry point declared in ``pyproject.toml``."""
    app()


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    main()
