"""``python -m speaker_roi_analytics.synthetic.cli`` - the operator's entry point.

**This module writes ground truth** (via :mod:`.generator`) and must never be
imported by ``speaker_roi_api`` or ``speaker_roi_worker``.

The CLI is deliberately thin. Every decision that affects the numbers lives in
:mod:`.config`; the only things a caller may vary are *which* profile, *which*
seed, and *where* it lands. In particular there is no ``--rows``, no
``--effect-size`` and no ``--noise`` flag: a dataset whose DGP can be tuned from
the command line is a dataset whose validation results cannot be reproduced from
the manifest alone.

``--generated-at`` exists for the same reason. The generator never reads the
clock, so a caller that wants a byte-identical manifest across runs pins the
timestamp; a caller that does not care gets "now", resolved *here*, at the edge.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.table import Table

from .config import PROFILES, ProfileName
from .generator import SyntheticMinimumNotMet, generate

__all__ = ["app", "main"]

app = typer.Typer(
    name="synthetic",
    help="Generate the deterministic synthetic dataset used to validate the causal engine.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _configure_logging(*, quiet: bool) -> None:
    """Human-readable structlog to stderr, so stdout stays parseable."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            40 if quiet else 20  # ERROR vs INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


@app.command("generate")
def generate_command(
    profile: Annotated[
        ProfileName,
        typer.Option("--profile", "-p", help="smoke (fast, CI) or full (PLAN_REVIEW F-2 volumes)."),
    ] = "smoke",
    seed: Annotated[
        int,
        typer.Option("--seed", "-s", help="The one number that determines every value produced."),
    ] = 20240501,
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output root. The profile name is appended to it."),
    ] = Path("data/synthetic"),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Replace an existing output directory."),
    ] = False,
    generated_at: Annotated[
        datetime | None,
        typer.Option(
            "--generated-at",
            help="Manifest timestamp. Pin it for a byte-identical manifest across runs.",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress per-stage progress logging."),
    ] = False,
) -> None:
    """Build one complete synthetic dataset and write it to ``--out/<profile>``."""
    _configure_logging(quiet=quiet)
    # typer parses --generated-at without a zone; the manifest must be
    # unambiguous, so a naive value is read as UTC rather than local time.
    stamp = generated_at or datetime.now(tz=UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)

    started = datetime.now(tz=UTC)
    try:
        dataset = generate(profile, seed, out, stamp, force=force)
    except SyntheticMinimumNotMet as exc:
        # Not a traceback: the operator needs the table, not our call stack.
        console.print(_assertion_table(exc.table, failed_only=False))
        console.print(f"[bold red]{exc.args[0].splitlines()[-1]}[/bold red]")
        raise typer.Exit(code=1) from None
    except FileExistsError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=2) from None
    elapsed = (datetime.now(tz=UTC) - started).total_seconds()

    console.print(_assertion_table(dataset.manifest["assertions"], failed_only=False))
    console.print(_volume_table(dataset.manifest))
    console.print(
        f"[bold green]{profile}[/bold green] seed=[bold]{seed}[/bold] "
        f"-> {out / profile}  ({elapsed:,.1f}s, "
        f"{sum(dataset.manifest['row_counts'].values()):,} gold rows, "
        f"{len(dataset.manifest['source_files'])} source files)"
    )


@app.command("profiles")
def profiles_command() -> None:
    """List the available profiles and their mandated volumes."""
    table = Table(title="Synthetic profiles (PLAN_REVIEW F-2)")
    table.add_column("profile")
    table.add_column("months", justify="right")
    table.add_column("hcps/tenant", justify="right")
    table.add_column("events", justify="right")
    table.add_column("min invitations", justify="right")
    table.add_column("min Rx rows", justify="right")
    for name, profile in PROFILES.items():
        targets = profile.targets
        table.add_row(
            name,
            f"{profile.months_of_history:,}",
            f"{targets.hcps_per_tenant:,}",
            f"{targets.events_total:,}",
            f"{targets.invitations:,}",
            f"{targets.rx_rows:,}",
        )
    Console().print(table)


def _assertion_table(rows: list[dict[str, object]], *, failed_only: bool) -> Table:
    """Render the actual-vs-required table the volume contract mandates."""
    table = Table(title="Volume and distribution assertions")
    table.add_column("quantity")
    table.add_column("actual", justify="right")
    table.add_column("required", justify="right")
    table.add_column("status", justify="center")
    for row in rows:
        ok = bool(row["ok"])
        if failed_only and ok:
            continue
        table.add_row(
            str(row["quantity"]),
            f"{int(row['actual']):,}",  # type: ignore[arg-type]
            f"{int(row['required']):,}",  # type: ignore[arg-type]
            "[green]ok[/green]" if ok else "[bold red]FAIL[/bold red]",
        )
    return table


def _volume_table(manifest: dict[str, object]) -> Table:
    """Per-frame row counts, so a short run is visible without opening parquet."""
    counts: dict[str, int] = manifest["row_counts"]  # type: ignore[assignment]
    truth: dict[str, int] = manifest["ground_truth_row_counts"]  # type: ignore[assignment]
    table = Table(title="Rows written")
    table.add_column("frame")
    table.add_column("rows", justify="right")
    for name, value in counts.items():
        table.add_row(name, f"{value:,}")
    for name, value in truth.items():
        table.add_row(f"[dim]ground_truth/{name}[/dim]", f"[dim]{value:,}[/dim]")
    return table


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover - exercised via the console script
    main()
