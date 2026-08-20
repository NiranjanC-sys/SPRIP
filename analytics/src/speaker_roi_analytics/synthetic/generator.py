"""Orchestration: one seed in, a complete reproducible dataset out.

**This module writes ground truth.** ``ground_truth/event_effects.parquet`` and
``ground_truth/hcp_latent.parquet`` contain the exact quantities the causal
engine is asked to recover. This module must never be imported by
``speaker_roi_api``, ``speaker_roi_worker``, or any feature builder - a test in
``tests/model_validation/test_synthetic_dgp.py`` walks the API source tree and
fails if it so much as mentions the ground-truth path.

Determinism contract
--------------------
``generate(profile, seed, out_dir, generated_at)`` is a pure function of its
arguments. In particular ``generated_at`` is *passed in*, never read from the
clock, because a timestamp in the manifest that changed per run would make the
manifest itself non-reproducible and quietly defeat the point of the seed.

Every stage draws from its own named RNG stream (``rng.RngBook``), so adding a
stage, or changing how many draws an existing stage makes, cannot shift the
numbers any other stage produces. That is what makes the DGP safe to extend.

Volume contract
---------------
PLAN_REVIEW F-2 fixes hard row minimums. They are not advisory: the ML and
causal work downstream is only meaningful at those volumes, and a dataset that
quietly came up short would produce underpowered results that look like model
failures. ``_assert_minimums`` therefore raises :class:`SyntheticMinimumNotMet`
with a full actual-vs-required table, and the CLI exits non-zero.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

from speaker_roi_core.enums import EventStatus

from . import costs as costs_mod
from . import events as events_mod
from . import exposure as exposure_mod
from . import hcps as hcps_mod
from . import imperfections as imperfections_mod
from . import outcomes as outcomes_mod
from . import source_files as source_mod
from . import taxonomy as taxonomy_mod
from .config import GENERATOR_VERSION, ProfileName, SyntheticProfile, get_profile
from .context import apply_program_halo, build_context
from .rng import RngBook

__all__ = [
    "GOLD_FRAMES",
    "GeneratedDataset",
    "SyntheticMinimumNotMet",
    "generate",
]

log = structlog.get_logger(__name__)

#: The gold layer, in dependency order. Every name here becomes
#: ``gold/{name}.parquet`` and gets a row count and a content hash in the
#: manifest.
GOLD_FRAMES: tuple[str, ...] = (
    "tenants",
    "vendors",
    "taxonomy_values",
    "brands",
    "products",
    "hcps",
    "hcp_crosswalk",
    "campaigns",
    "events",
    "invitations",
    "attendance",
    "rx_monthly",
    "marketing_activity",
    "market_factors",
    "event_costs",
    "finance_assumptions",
    "candidate_programs",
)

#: Written to ``ground_truth/``. Never part of the gold layer, never delivered
#: in ``source/``, never read by the platform.
TRUTH_FRAMES: tuple[str, ...] = ("event_effects", "hcp_latent")


class SyntheticMinimumNotMet(RuntimeError):
    """A profile produced fewer rows than PLAN_REVIEW F-2 requires."""

    def __init__(self, table: list[dict[str, Any]]) -> None:
        self.table = table
        failed = [row for row in table if not row["ok"]]
        lines = [
            "Synthetic generation did not meet the mandated row minimums.",
            "",
            f"{'quantity':<34}{'actual':>12}{'required':>12}  status",
            "-" * 72,
        ]
        lines.extend(
            f"{row['quantity']:<34}{row['actual']:>12,}{row['required']:>12,}"
            f"  {'ok' if row['ok'] else 'FAIL'}"
            for row in table
        )
        lines.append("")
        lines.append(f"{len(failed)} of {len(table)} checks failed.")
        super().__init__("\n".join(lines))


@dataclass(slots=True)
class GeneratedDataset:
    """Everything a run produced, in memory, before or after writing."""

    profile: SyntheticProfile
    seed: int
    frames: dict[str, pd.DataFrame]
    truth: dict[str, pd.DataFrame]
    manifest: dict[str, Any]


def generate(
    profile_name: ProfileName,
    seed: int,
    out_dir: Path,
    generated_at: datetime,
    *,
    force: bool = False,
    write: bool = True,
) -> GeneratedDataset:
    """Build (and by default write) one complete synthetic dataset.

    ``write=False`` is what the determinism test uses: it needs two in-memory
    runs to compare, and writing them would only measure the filesystem.
    """
    profile = get_profile(profile_name)
    book = RngBook(seed)
    target = out_dir / profile.name
    if write:
        _prepare_output(target, force=force)

    log.info("synthetic.start", profile=profile.name, seed=seed, out_dir=str(target))
    taxonomies, frames, truth, diagnostics = _build(profile, book)
    manifest = _manifest(profile, seed, generated_at, frames, truth, diagnostics)

    if write:
        _write(profile, taxonomies, frames, truth, manifest, target, book)
    log.info(
        "synthetic.done",
        profile=profile.name,
        gold_rows=sum(int(frames[name].shape[0]) for name in GOLD_FRAMES),
    )
    return GeneratedDataset(
        profile=profile, seed=seed, frames=frames, truth=truth, manifest=manifest
    )


def _build(
    profile: SyntheticProfile, book: RngBook
) -> tuple[
    taxonomy_mod.Taxonomies, dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, Any]
]:
    """Run every stage in dependency order, logging row counts as it goes."""
    taxonomies = taxonomy_mod.build_taxonomies(profile, book.stream("taxonomy"))
    _stage("taxonomy", tenants=taxonomies.tenants, brands=taxonomies.brands)

    universe = hcps_mod.build_hcps(profile, taxonomies, book.stream("hcps"))
    crosswalk = hcps_mod.build_crosswalk(universe, taxonomies.specs)
    _stage("hcps", hcps=universe.frame, crosswalk=crosswalk)

    context = build_context(profile, taxonomies, universe, book.stream("context"))
    _stage(
        "context",
        market_factors=context.market_factors,
        marketing_activity=context.marketing_activity,
    )

    plan = events_mod.build_events(profile, taxonomies, universe, book.stream("events"))
    _stage("events", campaigns=plan.campaigns, events=plan.events)

    membership = outcomes_mod.build_panel_membership(
        profile, taxonomies, universe, book.stream("outcomes")
    )
    invitations = exposure_mod.build_invitations(
        profile, taxonomies, universe, plan, membership, book.stream("invitations")
    )
    _stage("invitations", invitations=invitations.frame)

    # Field activity is raised around every invited program. This has to happen
    # after the invitation lists exist and before any outcome is drawn, because
    # rep calls enter the outcome model - see `ContextParams.halo_*`.
    context = apply_program_halo(
        profile,
        universe,
        context,
        invitations.hcp_row,
        plan.events["event_month_index"].to_numpy()[invitations.event_row],
        book.substream("context", 2),
    )
    _stage("halo", marketing_activity=context.marketing_activity)

    series = outcomes_mod.build_series(
        profile, taxonomies, universe, membership, book.stream("outcomes")
    )
    result = outcomes_mod.simulate_outcomes(
        profile, taxonomies, universe, plan, invitations, context, series, book
    )
    _stage("outcomes", rx_monthly=result.rx_monthly, attendance=result.attendance)

    event_costs = costs_mod.build_costs(profile, taxonomies, plan, book.stream("costs"))
    finance = costs_mod.build_finance_assumptions(profile, taxonomies, book.stream("costs"))
    _stage("costs", event_costs=event_costs, finance_assumptions=finance)

    frames: dict[str, pd.DataFrame] = {
        "tenants": taxonomies.tenants,
        "vendors": taxonomies.vendors,
        "taxonomy_values": taxonomies.taxonomy,
        "brands": taxonomies.brands,
        "products": taxonomies.products,
        "hcps": universe.frame,
        "hcp_crosswalk": crosswalk,
        "campaigns": plan.campaigns,
        "events": plan.events,
        "invitations": invitations.frame,
        "attendance": result.attendance,
        "rx_monthly": result.rx_monthly,
        "marketing_activity": context.marketing_activity,
        "market_factors": context.market_factors,
        "event_costs": event_costs,
        "finance_assumptions": finance,
        "candidate_programs": _candidate_programs(plan.events),
    }

    report = imperfections_mod.apply_imperfections(
        profile, plan, frames, book.stream("imperfections")
    )
    log.info("synthetic.stage", stage="imperfections", **report.counts)

    truth = {
        "event_effects": result.truth,
        "hcp_latent": hcps_mod.latent_truth_frame(universe),
    }
    diagnostics: dict[str, Any] = {
        **{k: _jsonable(v) for k, v in result.diagnostics.items()},
        "imperfections": report.counts,
    }
    return taxonomies, frames, truth, diagnostics


def _stage(name: str, **named_frames: pd.DataFrame) -> None:
    """Log one pipeline stage with the row count of everything it produced."""
    log.info(
        "synthetic.stage",
        stage=name,
        **{key: int(frame.shape[0]) for key, frame in named_frames.items()},
    )


def _candidate_programs(events: pd.DataFrame) -> pd.DataFrame:
    """Future programs, the forecaster's input (PLAN_REVIEW F-1, model M3).

    Deliberately *not* a copy of the event record: a candidate program has no
    realised attendance, no cost actuals and no outcome, and any column that
    only exists after a program has run would be a leak straight into the
    forecasting features.
    """
    proposed = events.loc[events["status"] == EventStatus.PROPOSED.value]
    columns = [
        "tenant_id",
        "event_id",
        "event_code",
        "campaign_id",
        "brand_id",
        "topic_code",
        "event_format",
        "region_code",
        "venue_city",
        "speaker_tier",
        "event_date",
        "planned_attendees",
    ]
    return proposed[columns].reset_index(drop=True)


def _jsonable(value: Any) -> Any:
    """numpy scalars are not JSON-serialisable; everything else passes through."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def _prepare_output(target: Path, *, force: bool) -> None:
    """Create the output tree, refusing to silently overwrite a previous run."""
    if target.exists():
        if not force:
            raise FileExistsError(
                f"{target} already exists. Pass --force to replace it, or choose "
                "another --out directory. Refusing to mix two runs in one tree."
            )
        shutil.rmtree(target)
    (target / "gold").mkdir(parents=True, exist_ok=True)
    (target / "ground_truth").mkdir(parents=True, exist_ok=True)


def _content_hash(frame: pd.DataFrame) -> str:
    """Value-sensitive SHA-256 of a frame's contents.

    Hashing the parquet bytes would be wrong: the writer embeds library versions
    and compression choices, so two identical datasets could hash differently.
    Hashing the *values* - column names, dtypes and a per-row digest - is what
    the determinism guarantee actually claims.
    """
    digest = hashlib.sha256()
    for column in frame.columns:
        digest.update(str(column).encode("utf-8"))
        digest.update(str(frame[column].dtype).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def _sorted_for_hash(frame: pd.DataFrame) -> pd.DataFrame:
    """Deterministic row order before hashing.

    Row order is an artefact of concatenation order, not of the data, so it is
    normalised away: two runs that produce the same rows must produce the same
    hash even if a stage internally reorders. Sorting on every column needs no
    per-frame key registry and cannot silently miss a tie.
    """
    return frame.sort_values(list(frame.columns), kind="stable").reset_index(drop=True)


def _assertion_table(
    profile: SyntheticProfile,
    frames: dict[str, pd.DataFrame],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Actual vs required for every mandated quantity (PLAN_REVIEW F-2)."""
    targets = profile.targets
    events = frames["events"]
    status = events["status"].to_numpy()
    completed = int((status == EventStatus.COMPLETED.value).sum())
    non_proposed = int((status != EventStatus.PROPOSED.value).sum())
    verified = int(frames["attendance"]["is_verified"].sum())

    checks: list[tuple[str, int, int]] = [
        ("tenants", int(frames["tenants"].shape[0]), targets.tenants),
        (
            "brands",
            int(frames["brands"].shape[0]),
            targets.brands_primary_tenant + targets.brands_secondary_tenant,
        ),
        ("hcps", int(frames["hcps"].shape[0]), targets.hcps_per_tenant * targets.tenants),
        ("campaigns", int(frames["campaigns"].shape[0]), targets.campaigns),
        ("events (all statuses)", int(events.shape[0]), targets.events_total),
        ("events COMPLETED", completed, targets.events_completed),
        (
            "events CANCELLED+PROPOSED",
            int(events.shape[0]) - completed,
            targets.events_not_completed,
        ),
        ("invitation rows", int(frames["invitations"].shape[0]), targets.invitations),
        ("verified attendance rows", verified, targets.verified_attendance),
        ("hcp-product-month Rx rows", int(frames["rx_monthly"].shape[0]), targets.rx_rows),
        (
            "marketing + market rows",
            int(frames["marketing_activity"].shape[0]) + int(frames["market_factors"].shape[0]),
            targets.marketing_and_market_rows,
        ),
        (
            "cost rows",
            int(frames["event_costs"].shape[0]),
            non_proposed * targets.cost_rows_per_event,
        ),
        ("months of history", profile.months_of_history, targets.months_of_history),
    ]
    table = [
        {"quantity": name, "actual": actual, "required": required, "ok": actual >= required}
        for name, actual, required in checks
    ]

    # Distributional gates. Not row counts, so they are rendered scaled by 1000
    # to stay integers in the same table, but they fail the run the same way: a
    # dataset with the right number of rows and the wrong attendance rate is
    # not usable either.
    selection = profile.selection
    rate = float(diagnostics["verified_attendance_rate"])
    table.append(
        {
            "quantity": "verified attendance rate x1000",
            "actual": round(rate * 1000),
            "required": round(selection.accepted_rate_lo * 1000),
            "ok": (selection.accepted_rate_lo <= rate <= selection.accepted_rate_hi),
        }
    )
    overlap = float(diagnostics["overlapping_exposure_rate"])
    ceiling = profile.imperfections.max_overlapping_exposure_rate
    table.append(
        {
            "quantity": "overlapping exposure x1000 (ceiling)",
            "actual": round(overlap * 1000),
            "required": round(ceiling * 1000),
            "ok": overlap <= ceiling,
        }
    )
    return table


def _manifest(
    profile: SyntheticProfile,
    seed: int,
    generated_at: datetime,
    frames: dict[str, pd.DataFrame],
    truth: dict[str, pd.DataFrame],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """Row counts, content hashes and the assertion table. Raises on shortfall."""
    table = _assertion_table(profile, frames, diagnostics)
    if any(not row["ok"] for row in table):
        raise SyntheticMinimumNotMet(table)

    return {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "profile": profile.name,
        "generated_at": generated_at.isoformat(),
        "months_of_history": profile.months_of_history,
        "panel_start_month": profile.panel_start_month.isoformat(),
        "row_counts": {name: int(frames[name].shape[0]) for name in GOLD_FRAMES},
        "checksums": {name: _content_hash(_sorted_for_hash(frames[name])) for name in GOLD_FRAMES},
        "ground_truth_row_counts": {name: int(truth[name].shape[0]) for name in TRUTH_FRAMES},
        "assertions": table,
        "diagnostics": diagnostics,
        "source_files": [],
    }


def _write(
    profile: SyntheticProfile,
    taxonomies: taxonomy_mod.Taxonomies,
    frames: dict[str, pd.DataFrame],
    truth: dict[str, pd.DataFrame],
    manifest: dict[str, Any],
    target: Path,
    book: RngBook,
) -> None:
    """Write gold, ground truth, the vendor source tree, then the manifest."""
    for name in GOLD_FRAMES:
        frames[name].to_parquet(target / "gold" / f"{name}.parquet", index=False)
    log.info("synthetic.written", layer="gold", frames=len(GOLD_FRAMES))

    for name in TRUTH_FRAMES:
        truth[name].to_parquet(target / "ground_truth" / f"{name}.parquet", index=False)
    log.info("synthetic.written", layer="ground_truth", frames=len(TRUTH_FRAMES))

    records = source_mod.write_source_files(
        profile, taxonomies, frames, target, book.stream("source_files")
    )
    manifest["source_files"] = [
        {
            "tenant_code": record.tenant_code,
            "dataset_type": record.dataset_type,
            "path": record.relative_path,
            "rows": record.row_count,
            "encoding": record.encoding,
            "format": record.file_format,
        }
        for record in records
    ]
    log.info("synthetic.written", layer="source", files=len(records))

    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
