"""What-if scenario management for budget optimization."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.common import Acknowledged, AuditStamp, Page
from speaker_roi_api.schemas.optimizer import ScenarioCreate, ScenarioOut
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.models.analytics import Scenario

router = APIRouter(tags=["Optimizer"])


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


def _scenario_out(row: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=row.id,
        name=row.name,
        brand_id=row.brand_id,
        budget_change_pct=0,
        event_count_change=0,
        projected_roi=float(row.budget_total) if row.budget_total is not None else None,
        projected_nrx=None,
        status=str(row.status),
        audit=_stamp(row),
    )


_AUDIT = ("code", "name", "brand_id", "status", "budget_total")


@router.post(
    "/optimizer/scenarios",
    response_model=ScenarioOut,
    status_code=201,
    summary="Create a what-if scenario",
    dependencies=[Depends(require(Permission.SCENARIO_WRITE)), Depends(deny_vendor)],
)
async def create_scenario(db: TenantSession, payload: ScenarioCreate) -> ScenarioOut:
    from datetime import date, timedelta

    today = date.today()
    row = await crud.create(
        db,
        Scenario,
        {
            "code": f"OPT-{uuid.uuid4().hex[:8].upper()}",
            "name": payload.name,
            "brand_id": payload.brand_id,
            "horizon_start": today,
            "horizon_end": today + timedelta(days=365),
            "budget_total": 0,
            "currency": "USD",
            "note": f"budget_change_pct={payload.budget_change_pct}, event_count_change={payload.event_count_change}",
        },
        resource="scenario",
        audit_fields=_AUDIT,
        label=payload.name,
        actor_id=_actor_id(),
    )
    return _scenario_out(row)


@router.get(
    "/optimizer/scenarios",
    response_model=Page[ScenarioOut],
    summary="List what-if scenarios",
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


@router.get(
    "/optimizer/scenarios/{scenario_id}",
    response_model=ScenarioOut,
    summary="Get a scenario with computed projections",
    dependencies=[Depends(require(Permission.SCENARIO_READ))],
)
async def get_scenario(db: ReadOnlySession, scenario_id: uuid.UUID) -> ScenarioOut:
    row = await crud.get_or_404(db, Scenario, scenario_id, resource="scenario")
    return _scenario_out(row)


@router.delete(
    "/optimizer/scenarios/{scenario_id}",
    response_model=Acknowledged,
    summary="Deactivate a scenario",
    dependencies=[Depends(require(Permission.SCENARIO_WRITE)), Depends(deny_vendor)],
)
async def deactivate_scenario(db: TenantSession, scenario_id: uuid.UUID) -> Acknowledged:
    row = await crud.get_or_404(db, Scenario, scenario_id, resource="scenario")
    await crud.deactivate(
        db,
        row,
        resource="scenario",
        audit_fields=_AUDIT,
        status_field="status",
        inactive_value="ARCHIVED",
        actor_id=_actor_id(),
    )
    return Acknowledged()


__all__ = ["router"]
