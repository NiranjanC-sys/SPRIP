"""Audit log viewer."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from speaker_roi_api.deps import PageParams, ReadOnlySession, require
from speaker_roi_api.schemas.common import Page
from speaker_roi_api.schemas.ingestion import AuditEventOut
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.models.audit import AuditEvent

router = APIRouter(tags=["Audit"])


def _out(row: AuditEvent) -> AuditEventOut:
    detail = {}
    if row.changed_fields:
        detail["changed_fields"] = row.changed_fields
    return AuditEventOut(
        id=row.id,
        action=str(row.action),
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        actor_id=row.actor_user_id,
        actor_email=row.actor_label,
        tenant_id=row.tenant_id,
        status_code=row.status_code,
        detail=detail or None,
        created_at=row.created_at,
        ip_address=row.ip_hash,
    )


@router.get(
    "/audit/events",
    response_model=Page[AuditEventOut],
    summary="List audit events",
    dependencies=[Depends(require(Permission.AUDIT_READ))],
)
async def list_audit_events(
    db: ReadOnlySession,
    page: PageParams,
    resource_type: Annotated[str | None, Query(alias="resourceType")] = None,
    action: Annotated[str | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query(alias="actorId")] = None,
    date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
) -> Page[AuditEventOut]:
    stmt = select(AuditEvent)
    if resource_type is not None:
        stmt = stmt.where(AuditEvent.resource_type == resource_type)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if actor_id is not None:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_id)
    if date_from is not None:
        stmt = stmt.where(AuditEvent.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditEvent.created_at <= date_to)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=AuditEvent.created_at, id_column=AuditEvent.id
    )
    return Page(items=[_out(r) for r in rows], next_cursor=cursor)


@router.get(
    "/audit/events/{audit_event_id}",
    response_model=AuditEventOut,
    summary="Get an audit event",
    dependencies=[Depends(require(Permission.AUDIT_READ))],
)
async def get_audit_event(db: ReadOnlySession, audit_event_id: uuid.UUID) -> AuditEventOut:
    row = await crud.get_or_404(db, AuditEvent, audit_event_id, resource="audit_event")
    return _out(row)


__all__ = ["router"]
