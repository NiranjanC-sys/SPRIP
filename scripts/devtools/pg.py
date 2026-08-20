"""Local PostgreSQL control for machines without Docker.

Runs the official PostgreSQL binaries out of ``.tools/pgsql`` (installed by
``scripts/devtools/install-postgres.ps1`` on Windows, or any ``pg_ctl`` already
on ``PATH`` elsewhere) against a private data directory under ``.tools/pgdata``.
No service, no administrator rights, no interference with anything else on the
machine.

Docker Compose remains the supported path; this is the escape hatch that
``scripts/verify`` falls back to when Docker is absent. It deliberately uses the
*same* PostgreSQL major version and the *same* contrib modules as the production
image - a development database that cannot hold the production schema (no
``btree_gist``, so no effective-dated ``EXCLUDE`` constraints) would let a broken
migration pass every local check.

The role split matters and is not a formality. ``app_migrator`` **owns** the
databases and schemas, which is what lets migrations run DDL and cross-tenant
backfills. ``app_rw`` owns nothing and holds no ``BYPASSRLS``, which is what
makes row-level security actually bind for the API. Collapsing the two would
leave every test passing and every tenant readable.

Usage:
    python scripts/devtools/pg.py start     # boot, provision, print the DSN
    python scripts/devtools/pg.py dsn       # migrator DSN for the app database
    python scripts/devtools/pg.py env       # env-var lines to paste into .env
    python scripts/devtools/pg.py status
    python scripts/devtools/pg.py reset     # drop and recreate the databases
    python scripts/devtools/pg.py stop
    python scripts/devtools/pg.py destroy   # stop and delete the data directory
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"
PGROOT = TOOLS / "pgsql"
PGDATA = TOOLS / "pgdata"
LOGFILE = TOOLS / "pgdata.log"

#: Fixed port so a regenerated ``.env`` stays valid across restarts. High enough
#: to avoid the ephemeral range on Windows and unlikely to collide with a real
#: PostgreSQL on 5432.
PORT = int(os.environ.get("DEV_PG_PORT", "54329"))
HOST = "127.0.0.1"

#: Superuser for the local cluster. Never used by the application.
SUPERUSER = "postgres"

APP_DB = "speaker_roi"
TEST_DB = "speaker_roi_test"
DATABASES = (APP_DB, TEST_DB)

#: Roles mirroring compose.yaml so the privilege model is identical in both
#: environments (docs/PLAN_REVIEW.md F-11). These development passwords never
#: leave the loopback interface and are not secrets.
ROLES: tuple[tuple[str, str, str], ...] = (
    ("app_migrator", "app_migrator_pw", "CREATEROLE"),
    ("app_rw", "app_rw_pw", ""),
    ("app_ro", "app_ro_pw", ""),
)
PASSWORDS = {role: pw for role, pw, _ in ROLES}

#: Contrib modules the schema genuinely needs. Checked at start so a stripped
#: build fails here with a clear message rather than 3,000 lines into a migration.
REQUIRED_EXTENSIONS = ("btree_gist", "pgcrypto", "pg_trgm")


# ---------------------------------------------------------------------------
# Locating the binaries
# ---------------------------------------------------------------------------


def _bin(name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    local = PGROOT / "bin" / exe
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(
        f"Could not find {name}. Install the portable server first:\n"
        f"  powershell -ExecutionPolicy Bypass -File scripts/devtools/install-postgres.ps1\n"
        f"or put an existing PostgreSQL 15+ bin directory on PATH."
    )


def _check_extensions() -> None:
    share = PGROOT / "share" / "extension"
    if not share.exists():
        return  # PATH install; trust the packager
    missing = [e for e in REQUIRED_EXTENSIONS if not (share / f"{e}.control").exists()]
    if missing:
        raise SystemExit(
            "This PostgreSQL build is missing contrib modules the schema needs: "
            + ", ".join(missing)
            + ".\nThe effective-dated EXCLUDE constraints cannot be created without "
            "btree_gist, so a database built here would not match production.\n"
            "Install the official binaries: "
            "powershell -ExecutionPolicy Bypass -File scripts/devtools/install-postgres.ps1"
        )


def _run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        args, capture_output=True, text=True, check=False, **kwargs
    )


def _run_detached(args: list[str]) -> int:
    """Run a command whose child outlives it, without capturing its streams.

    ``pg_ctl start`` hands the inherited stdout/stderr handles to the ``postgres``
    it spawns and then exits. If those handles are pipes, the pipe stays open for
    as long as the server runs, so ``capture_output=True`` blocks forever on a
    server that started perfectly. Send both streams to the null device and read
    the outcome from ``pg_ctl -l`` and :func:`_wait_ready` instead.
    """
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode


# ---------------------------------------------------------------------------
# Cluster lifecycle
# ---------------------------------------------------------------------------


def is_running() -> bool:
    if not PGDATA.exists():
        return False
    result = _run([_bin("pg_ctl"), "-D", str(PGDATA), "status"])
    return result.returncode == 0


def _initdb() -> None:
    PGDATA.parent.mkdir(parents=True, exist_ok=True)
    pwfile = TOOLS / ".superuser_pw"
    pwfile.write_text("postgres", encoding="utf-8")
    try:
        result = _run(
            [
                _bin("initdb"),
                "-D",
                str(PGDATA),
                "-U",
                SUPERUSER,
                "--pwfile",
                str(pwfile),
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
                "--encoding=UTF8",
                "--locale=C",
            ]
        )
    finally:
        pwfile.unlink(missing_ok=True)
    if result.returncode != 0:
        raise SystemExit(f"initdb failed:\n{result.stdout}\n{result.stderr}")

    # Bind loopback only. A development database holding synthetic prescriber
    # data still should not be reachable from the office network.
    conf = PGDATA / "postgresql.conf"
    conf.write_text(
        conf.read_text(encoding="utf-8") + "\n# --- speaker-roi development overrides ---\n"
        f"listen_addresses = '{HOST}'\n"
        f"port = {PORT}\n"
        "max_connections = 100\n"
        "shared_buffers = 256MB\n"
        "work_mem = 16MB\n"
        # Both settings, not just the first: `timezone` governs how sessions
        # resolve timestamps, `log_timezone` governs the log prefix. Leaving the
        # latter local makes a developer's log lines uncomparable with CI's.
        "timezone = 'UTC'\n"
        "log_timezone = 'UTC'\n"
        "log_min_duration_statement = 2000\n"
        "log_line_prefix = '%m [%p] %q%u@%d '\n",
        encoding="utf-8",
    )


def _psql(sql: str, database: str = "postgres") -> str:
    """Run one statement as the local superuser and return its output.

    Callers interpolate role and database *identifiers* into the SQL, which ruff
    flags as S608. There is no bind parameter for an identifier in any SQL
    dialect, and every value interpolated here comes from the ``ROLES`` and
    ``DATABASES`` constants above - this script takes no external input at all,
    so the flagged sites are suppressed individually rather than worked around.
    """
    result = _run(
        [
            _bin("psql"),
            "-v",
            "ON_ERROR_STOP=1",
            "-X",
            "-q",
            "-A",
            "-t",
            "-h",
            HOST,
            "-p",
            str(PORT),
            "-U",
            SUPERUSER,
            "-d",
            database,
            "-c",
            sql,
        ],
        env={**os.environ, "PGPASSWORD": "postgres"},
    )
    if result.returncode != 0:
        raise SystemExit(f"psql failed on {database}:\n{sql}\n{result.stderr}")
    return result.stdout.strip()


def _wait_ready(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _run([_bin("pg_isready"), "-h", HOST, "-p", str(PORT)]).returncode == 0:
            return
        time.sleep(0.4)
    raise SystemExit(f"server did not become ready within {timeout:.0f}s; see {LOGFILE}")


def start() -> str:
    _check_extensions()
    if not (PGDATA / "PG_VERSION").exists():
        _initdb()
    if not is_running():
        code = _run_detached(
            [_bin("pg_ctl"), "-D", str(PGDATA), "-l", str(LOGFILE), "-w", "-t", "60", "start"]
        )
        if code != 0:
            log = (
                LOGFILE.read_text(encoding="utf-8", errors="replace")[-2000:]
                if LOGFILE.exists()
                else "(no log written)"
            )
            raise SystemExit(f"pg_ctl start failed (exit {code}):\n{log}")
    _wait_ready()
    provision()
    return dsn()


def provision() -> None:
    """Roles, databases and ownership. Idempotent."""
    for role, pw, extra in ROLES:
        _psql(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "  # noqa: S608
            f"THEN CREATE ROLE {role} LOGIN PASSWORD '{pw}' {extra}; END IF; END $$;"
        )
    for db in DATABASES:
        exists = _psql(f"SELECT 1 FROM pg_database WHERE datname='{db}'")  # noqa: S608
        if exists != "1":
            _psql(f'CREATE DATABASE "{db}" OWNER app_migrator')
        # Ownership, not merely privileges: the migration revokes PUBLIC access
        # to the database, which requires the migrating role to own it.
        _psql(f'ALTER DATABASE "{db}" OWNER TO app_migrator')
        _psql(f'GRANT CONNECT ON DATABASE "{db}" TO app_rw, app_ro')


def stop() -> None:
    if PGDATA.exists() and is_running():
        _run([_bin("pg_ctl"), "-D", str(PGDATA), "-m", "fast", "-w", "stop"])


def reset() -> None:
    """Drop and recreate both databases. Keeps roles and the cluster."""
    if not is_running():
        start()
    for db in DATABASES:
        _psql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "  # noqa: S608
            f"WHERE datname='{db}' AND pid <> pg_backend_pid()"
        )
        _psql(f'DROP DATABASE IF EXISTS "{db}"')
    provision()


def destroy() -> None:
    """Stop and delete the whole cluster. Recoverable only by re-running start."""
    stop()
    if PGDATA.exists():
        shutil.rmtree(PGDATA, ignore_errors=True)
    LOGFILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Connection strings
# ---------------------------------------------------------------------------


def url_for(role: str, database: str, driver: str = "psycopg") -> str:
    return f"postgresql+{driver}://{role}:{PASSWORDS[role]}@{HOST}:{PORT}/{database}"


def dsn() -> str:
    return url_for("app_migrator", APP_DB)


def env_lines() -> list[str]:
    """Every variable the application and Alembic need, in both shapes they read.

    The two shapes are not redundant and getting this wrong wastes an afternoon.
    ``speaker_roi_core.config.DatabaseSettings`` *composes* a URL from ``DB_HOST``,
    ``DB_PORT``, ``DB_NAME``, ``DB_USER`` and ``DB_PASSWORD`` - it never reads
    ``DATABASE_URL`` - because a single URL cannot express the migrator/application role
    split, the pool sizes or the statement timeouts, and splitting it later means parsing a
    URL we just assembled. ``migrations/env.py`` reads ``MIGRATION_DATABASE_URL`` because
    Alembic is handed a URL by design.

    So a developer who exports only the URLs gets an application that silently connects to
    ``localhost:5432`` on the defaults, and one who exports only the ``DB_*`` fields gets
    migrations that refuse to run. Emitting both is the fix; emitting one and documenting
    the other is what produced this comment.
    """
    return [
        "# Generated by: python scripts/devtools/pg.py env",
        "# The DB_* fields configure the application (pool, timeouts, role split).",
        f"DB_HOST={HOST}",
        f"DB_PORT={PORT}",
        f"DB_NAME={APP_DB}",
        "DB_USER=app_rw",
        f"DB_PASSWORD={PASSWORDS['app_rw']}",
        "DB_MIGRATION_USER=app_migrator",
        f"DB_MIGRATION_PASSWORD={PASSWORDS['app_migrator']}",
        "",
        "# The URL forms are what Alembic reads.",
        f"MIGRATION_DATABASE_URL={url_for('app_migrator', APP_DB)}",
        f"DATABASE_URL={url_for('app_rw', APP_DB, 'asyncpg')}",
        f"READONLY_DATABASE_URL={url_for('app_ro', APP_DB, 'asyncpg')}",
        f"TEST_MIGRATION_DATABASE_URL={url_for('app_migrator', TEST_DB)}",
        f"TEST_DATABASE_URL={url_for('app_rw', TEST_DB, 'asyncpg')}",
    ]


def status() -> str:
    if not PGDATA.exists():
        return "not initialised"
    if not is_running():
        return "stopped"
    version = _psql("SHOW server_version")
    dbs = _psql(
        "SELECT string_agg(datname, ', ' ORDER BY datname) FROM pg_database "
        "WHERE datname LIKE 'speaker_roi%'"
    )
    return f"running  PostgreSQL {version}  port {PORT}  databases: {dbs or '-'}"


COMMANDS = {
    "start": lambda: print(start()),
    "dsn": lambda: print(dsn()),
    "env": lambda: print("\n".join(env_lines())),
    "status": lambda: print(status()),
    "provision": provision,
    "reset": lambda: (reset(), print(dsn())),
    "stop": lambda: (stop(), print("stopped")),
    "destroy": lambda: (destroy(), print("destroyed")),
}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    handler = COMMANDS.get(command)
    if handler is None:
        raise SystemExit(f"unknown command: {command}\nknown: {', '.join(COMMANDS)}")
    handler()
