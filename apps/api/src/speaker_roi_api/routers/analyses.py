"""Analyses, event impacts, forecasts and budget scenarios."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.analyses import (
    AnalysisRunCreate,
    AnalysisRunOut,
    EventImpactOut,
    ForecastOut,
    ScenarioCreate,
    ScenarioOut,
    ScenarioPatch,
)
from speaker_roi_api.schemas.common import AuditStamp, Page
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.models.analytics import (
    AnalysisRun,
    EventImpact,
    Forecast,
    Scenario,
)

router = APIRouter(tags=["Analytics"])


def _stamp(row: Any) -> AuditStamp:
    return AuditStamp(
        created_at=row.created_at,
        updated_at=getattr(row, "updated_at", None),
        created_by=getattr(row, "created_by", None),
        updated_by=getattr(row, "updated_by", None),
        version=getattr(row, "row_version", None),
    )


def _actor_id() -> uuid.UUID | None:
    principal = current_principal()
    return principal.user_id if principal else None


def _run_out(row: AnalysisRun) -> AnalysisRunOut:
    return AnalysisRunOut(
        id=row.id,
        brand_id=getattr(row, "brand_id", None) or (row.parameters or {}).get("brand_id"),
        analysis_type=str(row.run_kind),
        status=str(row.status),
        started_at=row.started_at,
        completed_at=row.finished_at,
        config=row.parameters,
        result_summary=None,
        audit=_stamp(row),
    )


def _impact_out(row: EventImpact) -> EventImpactOut:
    return EventImpactOut(
        id=row.id,
        event_id=row.event_id,
        run_id=row.run_id,
        brand_id=row.brand_id,
        outcome_metric=str(row.outcome_metric),
        att=float(row.att) if row.att is not None else None,
        incremental_nrx=float(row.incremental_nrx) if row.incremental_nrx is not None else None,
        p_value=float(row.p_value) if row.p_value is not None else None,
        ci_low=float(row.ci_low) if row.ci_low is not None else None,
        ci_high=float(row.ci_high) if row.ci_high is not None else None,
        evidence_status=str(row.evidence_status),
        evidence_grade=str(row.evidence_grade),
        n_treated=row.n_treated,
        n_control=row.n_control,
        audit=_stamp(row),
    )


def _forecast_out(row: Forecast) -> ForecastOut:
    return ForecastOut(
        id=row.id,
        run_id=row.run_id,
        brand_id=row.brand_id,
        scenario_id=row.scenario_id,
        candidate_program_id=row.candidate_program_id,
        mode=str(row.mode),
        point_estimate=float(row.point_estimate) if row.point_estimate is not None else None,
        pi_low=float(row.pi_low) if row.pi_low is not None else None,
        pi_high=float(row.pi_high) if row.pi_high is not None else None,
        n_effective=float(row.n_effective) if row.n_effective is not None else None,
    )


def _scenario_out(row: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=row.id,
        code=row.code,
        name=row.name,
        brand_id=row.brand_id,
        status=str(row.status),
        horizon_start=row.horizon_start,
        horizon_end=row.horizon_end,
        budget_total=float(row.budget_total),
        currency=row.currency,
        note=row.note,
        audit=_stamp(row),
    )


# ---------------------------------------------------------------------------
# Analysis runs
# ---------------------------------------------------------------------------


@router.get(
    "/analyses/runs",
    response_model=Page[AnalysisRunOut],
    summary="List analysis runs",
    dependencies=[Depends(require(Permission.ANALYSIS_READ))],
)
async def list_runs(
    db: ReadOnlySession,
    page: PageParams,
    status: Annotated[str | None, Query()] = None,
) -> Page[AnalysisRunOut]:
    stmt = select(AnalysisRun)
    if status is not None:
        stmt = stmt.where(AnalysisRun.status == status)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=AnalysisRun.created_at, id_column=AnalysisRun.id
    )
    return Page(items=[_run_out(r) for r in rows], next_cursor=cursor)


@router.get(
    "/analyses/runs/{run_id}",
    response_model=AnalysisRunOut,
    summary="Get an analysis run",
    dependencies=[Depends(require(Permission.ANALYSIS_READ))],
)
async def get_run(db: ReadOnlySession, run_id: uuid.UUID) -> AnalysisRunOut:
    row = await crud.get_or_404(db, AnalysisRun, run_id, resource="analysis_run")
    return _run_out(row)


@router.post(
    "/analyses/runs",
    response_model=AnalysisRunOut,
    status_code=201,
    summary="Start an analysis run",
    dependencies=[Depends(require(Permission.ANALYSIS_RUN))],
)
async def create_run(db: TenantSession, payload: AnalysisRunCreate) -> AnalysisRunOut:
    row = await crud.create(
        db,
        AnalysisRun,
        {
            "run_kind": payload.analysis_type,
            "parameters": payload.config or {},
            "requested_by": _actor_id(),
        },
        resource="analysis_run",
        audit_fields=("run_kind", "status"),
        label=payload.analysis_type,
        actor_id=_actor_id(),
    )
    return _run_out(row)


# ---------------------------------------------------------------------------
# Event impacts
# ---------------------------------------------------------------------------


@router.get(
    "/analyses/impacts",
    response_model=Page[EventImpactOut],
    summary="List event impacts",
    dependencies=[Depends(require(Permission.ANALYSIS_READ))],
)
async def list_impacts(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
    event_id: Annotated[uuid.UUID | None, Query(alias="eventId")] = None,
    evidence_status: Annotated[str | None, Query(alias="evidenceStatus")] = None,
) -> Page[EventImpactOut]:
    stmt = select(EventImpact)
    if brand_id is not None:
        stmt = stmt.where(EventImpact.brand_id == brand_id)
    if event_id is not None:
        stmt = stmt.where(EventImpact.event_id == event_id)
    if evidence_status is not None:
        stmt = stmt.where(EventImpact.evidence_status == evidence_status)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=EventImpact.created_at, id_column=EventImpact.id
    )
    return Page(items=[_impact_out(r) for r in rows], next_cursor=cursor)


@router.get(
    "/analyses/impacts/{impact_id}",
    response_model=EventImpactOut,
    summary="Get an event impact",
    dependencies=[Depends(require(Permission.ANALYSIS_READ))],
)
async def get_impact(db: ReadOnlySession, impact_id: uuid.UUID) -> EventImpactOut:
    row = await crud.get_or_404(db, EventImpact, impact_id, resource="event_impact")
    return _impact_out(row)


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------


@router.get(
    "/forecasts",
    response_model=Page[ForecastOut],
    summary="List forecasts",
    dependencies=[Depends(require(Permission.FORECAST_READ))],
)
async def list_forecasts(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
    scenario_id: Annotated[uuid.UUID | None, Query(alias="scenarioId")] = None,
) -> Page[ForecastOut]:
    stmt = select(Forecast)
    if brand_id is not None:
        stmt = stmt.where(Forecast.brand_id == brand_id)
    if scenario_id is not None:
        stmt = stmt.where(Forecast.scenario_id == scenario_id)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Forecast.created_at, id_column=Forecast.id
    )
    return Page(items=[_forecast_out(r) for r in rows], next_cursor=cursor)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@router.get(
    "/scenarios",
    response_model=Page[ScenarioOut],
    summary="List scenarios",
    dependencies=[Depends(require(Permission.SCENARIO_READ))],
)
async def list_scenarios(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
) -> Page[ScenarioOut]:
    stmt = select(Scenario)
    if brand_id is not None:
        stmt = stmt.where(Scenario.brand_id == brand_id)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Scenario.created_at, id_column=Scenario.id
    )
    return Page(items=[_scenario_out(r) for r in rows], next_cursor=cursor)


@router.post(
    "/scenarios",
    response_model=ScenarioOut,
    status_code=201,
    summary="Create a budget scenario",
    dependencies=[Depends(require(Permission.SCENARIO_WRITE)), Depends(deny_vendor)],
)
async def create_scenario(db: TenantSession, payload: ScenarioCreate) -> ScenarioOut:
    row = await crud.create(
        db,
        Scenario,
        payload.model_dump(exclude_unset=True),
        resource="scenario",
        audit_fields=("code", "name", "brand_id", "status", "budget_total"),
        label=payload.code,
        actor_id=_actor_id(),
    )
    return _scenario_out(row)


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioOut,
    summary="Get a scenario",
    dependencies=[Depends(require(Permission.SCENARIO_READ))],
)
async def get_scenario(db: ReadOnlySession, scenario_id: uuid.UUID) -> ScenarioOut:
    row = await crud.get_or_404(db, Scenario, scenario_id, resource="scenario")
    return _scenario_out(row)


@router.patch(
    "/scenarios/{scenario_id}",
    response_model=ScenarioOut,
    summary="Update a scenario",
    dependencies=[Depends(require(Permission.SCENARIO_WRITE)), Depends(deny_vendor)],
)
async def patch_scenario(
    db: TenantSession, scenario_id: uuid.UUID, payload: ScenarioPatch
) -> ScenarioOut:
    row = await crud.get_or_404(db, Scenario, scenario_id, resource="scenario")
    await crud.update(
        db,
        row,
        crud.patch_changes(payload, "name", "budget_total", "note"),
        resource="scenario",
        audit_fields=("code", "name", "brand_id", "status", "budget_total"),
        expected_version=payload.version,
        label=row.code,
        actor_id=_actor_id(),
    )
    return _scenario_out(row)


__all__ = ["router"]
