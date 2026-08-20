"""Local Redis and object storage for machines without Docker.

The companion to ``pg.py``, and it exists for the same reason: Docker Compose is the
supported path, but a developer without Docker still has to be able to run the whole system,
and "the API starts but every upload fails" is not a working development environment.

Runs the real implementations - a Redis server and MinIO, which speaks the S3 API - out of
``.tools``, against private data directories, on loopback only. No service registration, no
administrator rights, nothing that outlives ``services.py stop``.

Both listen on non-default ports (``63799`` and ``9100``) for the same reason ``pg.py`` uses
``54329``: a developer may already have a Redis or a MinIO running, and silently sharing one
is worse than not starting. A shared Redis in particular means one project's ``FLUSHDB``
during a test run empties another's cache, and the symptom appears in the *other* project.

Usage:
    python scripts/devtools/services.py start     # boot both, create the buckets
    python scripts/devtools/services.py status
    python scripts/devtools/services.py env       # env-var lines to paste into .env
    python scripts/devtools/services.py stop
    python scripts/devtools/services.py destroy   # stop and delete the data directories
"""

from __future__ import annotations

import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"

HOST = "127.0.0.1"

REDIS_DIR = TOOLS / "redis"
REDIS_DATA = TOOLS / "redisdata"
REDIS_LOG = TOOLS / "redisdata.log"
REDIS_PORT = int(os.environ.get("DEV_REDIS_PORT", "63799"))

MINIO_DIR = TOOLS / "minio"
MINIO_DATA = TOOLS / "miniodata"
MINIO_LOG = TOOLS / "miniodata.log"
MINIO_PORT = int(os.environ.get("DEV_MINIO_PORT", "9100"))
MINIO_CONSOLE_PORT = int(os.environ.get("DEV_MINIO_CONSOLE_PORT", "9101"))

#: Development credentials. They never leave loopback and are not secrets, which is why they
#: are in the file rather than in an environment variable - a placeholder that has to be
#: looked up somewhere else is how a developer ends up putting a real key here instead.
MINIO_USER = "minioadmin"
MINIO_PASSWORD = "minioadmin"  # noqa: S105 - loopback development default, not a secret

#: Must match ``StorageSettings``. Three buckets rather than three prefixes in one, because
#: they have genuinely different lifecycle and access rules: uploads are retained under the
#: tenant's retention policy, exports expire in days, artifacts are keyed by model version.
BUCKETS = ("speaker-roi-uploads", "speaker-roi-exports", "speaker-roi-artifacts")

_PID_FILES = {"redis": TOOLS / "redisdata.pid", "minio": TOOLS / "miniodata.pid"}


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _exe(directory: Path, stem: str) -> str:
    """Locate a binary in ``.tools``, falling back to ``PATH``.

    The fallback is what makes this script work on Linux and macOS, where the developer
    installed ``redis-server`` and ``minio`` through a package manager and there is nothing
    under ``.tools`` at all.
    """
    for candidate in (directory / f"{stem}.exe", directory / stem):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(stem)
    if found:
        return found
    raise SystemExit(
        f"{stem} not found in {directory} or on PATH.\n"
        f"  Windows: see docs/runbook.md#local-services for the download,\n"
        f"  macOS:   brew install redis minio/stable/minio\n"
        f"  Linux:   your package manager, or use compose.yaml instead."
    )


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.35)
        return probe.connect_ex((HOST, port)) == 0


def _spawn(name: str, argv: list[str], logfile: Path) -> None:
    """Start a detached background process, recording its pid.

    ``start_new_session`` / ``DETACHED_PROCESS`` is the load-bearing part: without it the
    child shares this script's console, and it dies the moment the shell that invoked
    ``services.py start`` exits - which looks exactly like a crash on startup.
    """
    logfile.parent.mkdir(parents=True, exist_ok=True)
    handle = logfile.open("ab")
    kwargs: dict[str, object] = {"stdout": handle, "stderr": handle, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    # S603: argv[0] comes from _exe, which resolves a fixed binary name under .tools or PATH.
    process = subprocess.Popen(argv, cwd=str(ROOT), **kwargs)  # type: ignore[call-overload] # noqa: S603
    _PID_FILES[name].write_text(str(process.pid), encoding="utf-8")


def _await_port(port: int, label: str, logfile: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            return
        time.sleep(0.25)
    tail = ""
    if logfile.exists():
        tail = "\n".join(logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
    raise SystemExit(f"{label} did not open port {port} within {timeout:.0f}s.\n{tail}")


def _kill(name: str) -> None:
    """Stop by recorded pid, never by process name.

    ``taskkill /IM redis-server.exe`` would also kill a Redis the developer is running for
    something else, which is precisely the interference the non-default ports exist to avoid.
    """
    pid_file = _PID_FILES[name]
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return
    if sys.platform == "win32":
        # Absolute path: resolving "taskkill" through PATH would run whatever a directory
        # earlier on PATH happens to call taskkill.exe.
        taskkill = str(
            pathlib.Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        )
        subprocess.run(  # noqa: S603
            [taskkill, "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            check=False,
        )
    else:
        import contextlib
        import signal

        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    pid_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def start_redis() -> None:
    if _port_open(REDIS_PORT):
        return
    REDIS_DATA.mkdir(parents=True, exist_ok=True)
    _spawn(
        "redis",
        [
            _exe(REDIS_DIR, "redis-server"),
            "--port",
            str(REDIS_PORT),
            # Loopback only. The Windows Redis port has no protected-mode equivalent worth
            # relying on, so the bind is the control.
            "--bind",
            HOST,
            "--dir",
            str(REDIS_DATA),
            "--dbfilename",
            "dev.rdb",
            # Celery brokers a queue through this; losing it on a laptop reboot is fine, but
            # losing it mid-session because a snapshot failed is not, so snapshots are off and
            # persistence is best-effort on shutdown only.
            "--save",
            "",
            "--appendonly",
            "no",
            # A runaway analysis fan-out should fail loudly rather than consume the machine.
            "--maxmemory",
            "512mb",
            "--maxmemory-policy",
            "noeviction",
        ],
        REDIS_LOG,
    )
    _await_port(REDIS_PORT, "redis", REDIS_LOG)


def redis_url(db: int = 0) -> str:
    return f"redis://{HOST}:{REDIS_PORT}/{db}"


# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------


def start_minio() -> None:
    if _port_open(MINIO_PORT):
        return
    MINIO_DATA.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["MINIO_ROOT_USER"] = MINIO_USER
    environment["MINIO_ROOT_PASSWORD"] = MINIO_PASSWORD
    # MinIO refuses to start with a root password under eight characters, and the message it
    # prints is about the API rather than the variable, so the check is here instead.
    if len(MINIO_PASSWORD) < 8:
        raise SystemExit("MINIO_ROOT_PASSWORD must be at least 8 characters")

    logfile = MINIO_LOG
    logfile.parent.mkdir(parents=True, exist_ok=True)
    handle = logfile.open("ab")
    argv = [
        _exe(MINIO_DIR, "minio"),
        "server",
        str(MINIO_DATA),
        "--address",
        f"{HOST}:{MINIO_PORT}",
        "--console-address",
        f"{HOST}:{MINIO_CONSOLE_PORT}",
    ]
    kwargs: dict[str, object] = {
        "stdout": handle,
        "stderr": handle,
        "stdin": subprocess.DEVNULL,
        "env": environment,
        "cwd": str(ROOT),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **kwargs)  # type: ignore[call-overload] # noqa: S603
    _PID_FILES["minio"].write_text(str(process.pid), encoding="utf-8")
    _await_port(MINIO_PORT, "minio", logfile, timeout=45.0)
    _await_ready()


def _await_ready(timeout: float = 30.0) -> None:
    """Wait for MinIO's health endpoint, not just its port.

    The listener opens before the object layer is initialised, so a ``create_bucket`` issued
    on the strength of an open port gets ``ServerNotInitialized`` - intermittently, and more
    often on a cold disk, which makes it look like a flaky test rather than a race here.
    """
    url = f"http://{HOST}:{MINIO_PORT}/minio/health/live"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.4)
    raise SystemExit(f"minio port {MINIO_PORT} is open but it never reported healthy")


def endpoint_url() -> str:
    return f"http://{HOST}:{MINIO_PORT}"


def ensure_buckets() -> list[str]:
    """Create the three buckets. Idempotent, and it never touches bucket policy.

    Deliberately does not make anything public. The production buckets are private and every
    download goes through a short-lived presigned URL, so a development bucket that is world
    readable would let a broken presign path pass every local test.
    """
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url(),
        aws_access_key_id=MINIO_USER,
        aws_secret_access_key=MINIO_PASSWORD,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    created = []
    for bucket in BUCKETS:
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            client.create_bucket(Bucket=bucket)
            created.append(bucket)
    return created


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def start() -> str:
    start_redis()
    start_minio()
    created = ensure_buckets()
    note = f"  created buckets: {', '.join(created)}" if created else "  buckets already present"
    return f"redis  {redis_url()}\nminio  {endpoint_url()}\n{note}"


def stop() -> None:
    _kill("redis")
    _kill("minio")


def destroy() -> None:
    stop()
    for path in (REDIS_DATA, MINIO_DATA):
        shutil.rmtree(path, ignore_errors=True)
    for path in (REDIS_LOG, MINIO_LOG):
        path.unlink(missing_ok=True)


def status() -> str:
    lines = []
    for label, port in (("redis", REDIS_PORT), ("minio", MINIO_PORT)):
        state = "running" if _port_open(port) else "stopped"
        lines.append(f"{label:<6} {state:<8} port {port}")
    return "\n".join(lines)


def env_lines() -> list[str]:
    """The variables the application reads, in the shape it reads them.

    ``RedisSettings`` composes its URL from ``REDIS_HOST``/``REDIS_PORT`` and the three
    database numbers rather than taking a URL, for the same reason ``DatabaseSettings`` does:
    one URL cannot express the broker/result/cache split, and Celery needs the broker and the
    result backend to be *different* databases or a purge of one discards the other.
    """
    return [
        "# Generated by: python scripts/devtools/services.py env",
        f"REDIS_HOST={HOST}",
        f"REDIS_PORT={REDIS_PORT}",
        "REDIS_BROKER_DB=0",
        "REDIS_RESULT_DB=1",
        "REDIS_CACHE_DB=2",
        "",
        f"STORAGE_ENDPOINT_URL={endpoint_url()}",
        "STORAGE_REGION=us-east-1",
        f"STORAGE_ACCESS_KEY={MINIO_USER}",
        f"STORAGE_SECRET_KEY={MINIO_PASSWORD}",
        "STORAGE_USE_PATH_STYLE=true",
        f"STORAGE_UPLOAD_BUCKET={BUCKETS[0]}",
        f"STORAGE_EXPORT_BUCKET={BUCKETS[1]}",
        f"STORAGE_ARTIFACT_BUCKET={BUCKETS[2]}",
    ]


COMMANDS = {
    "start": lambda: print(start()),
    "status": lambda: print(status()),
    "env": lambda: print("\n".join(env_lines())),
    "buckets": lambda: print(", ".join(ensure_buckets()) or "already present"),
    "stop": lambda: (stop(), print("stopped")),
    "destroy": lambda: (destroy(), print("destroyed")),
}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    handler = COMMANDS.get(command)
    if handler is None:
        raise SystemExit(f"unknown command: {command}\nknown: {', '.join(COMMANDS)}")
    handler()
