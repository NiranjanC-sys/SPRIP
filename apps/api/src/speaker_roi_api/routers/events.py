"""Speaker program events - the atomic unit of measurement.

Each event belongs to a brand and optionally a campaign. Speakers (HCPs or external experts)
are attached as nested resources.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.common import Acknowledged, AuditStamp, Page
from speaker_roi_api.schemas.events import (
    EventCreate,
    EventOut,
    EventPatch,
    EventSpeakerIn,
    EventSpeakerOut,
)
from speaker_roi_api.schemas.master_data import DeactivateRequest
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import audit, crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.enums import AuditAction, EventStatus
from speaker_roi_core.errors import NotFoundError, ValidationError
from speaker_roi_core.models.core import Brand, Event, EventSpeaker

router = APIRouter(tags=["Events"])

_EVENT_AUDIT = (
    "code",
    "name",
    "brand_id",
    "campaign_id",
    "event_date",
    "format",
    "status",
    "planned_attendance",
    "measurement_eligible",
)
_SPEAKER_AUDIT = ("event_id", "hcp_id", "external_speaker_code", "tier", "honorarium_amount")


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


def _speaker_out(row: EventSpeaker) -> EventSpeakerOut:
    return EventSpeakerOut(
        id=row.id,
        event_id=row.event_id,
        hcp_id=row.hcp_id,
        external_speaker_code=row.external_speaker_code,
        tier=row.tier,
        speaking_role=row.speaking_role,
        honorarium_amount=row.honorarium_amount,
        currency=row.currency,
    )


def _event_out(
    row: Event,
    *,
    brand_name: str | None = None,
    speaker_count: int | None = None,
    include_speakers: bool = False,
) -> EventOut:
    return EventOut(
        id=row.id,
        code=row.code,
        name=row.name,
        brand_id=row.brand_id,
        brand_name=brand_name,
        campaign_id=row.campaign_id,
        event_date=row.event_date,
        start_time=row.start_time,
        end_time=row.end_time,
        timezone=row.timezone,
        format=str(row.format),
        topic_code=row.topic_code,
        region_code=row.region_code,
        venue_city=row.venue_city,
        venue_name=row.venue_name,
        speaker_tier=row.speaker_tier,
        planned_attendance=row.planned_attendance,
        status=str(row.status),
        workflow_status=str(row.workflow_status),
        measurement_eligible=row.measurement_eligible,
        exclusion_reason=str(row.exclusion_reason) if row.exclusion_reason else None,
        speaker_count=speaker_count,
        speakers=[_speaker_out(s) for s in row.speakers] if include_speakers else None,
        audit=_stamp(row),
    )


def _assert_brand_visible(brand_id: uuid.UUID) -> None:
    from speaker_roi_core.errors import ForbiddenError

    principal = current_principal()
    if principal is not None and not principal.may_see_brand(brand_id):
        raise ForbiddenError(
            "Your access is limited to a subset of brands, and this is not one of them.",
            remediation="Ask an administrator to widen your brand access.",
        )


@router.get(
    "/events",
    response_model=Page[EventOut],
    summary="List events",
    dependencies=[Depends(require(Permission.EVENT_READ))],
)
async def list_events(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
    campaign_id: Annotated[uuid.UUID | None, Query(alias="campaignId")] = None,
    event_status: Annotated[EventStatus | None, Query(alias="status")] = None,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> Page[EventOut]:
    principal = current_principal()
    stmt = select(Event).options(selectinload(Event.brand))
    if brand_id is not None:
        _assert_brand_visible(brand_id)
        stmt = stmt.where(Event.brand_id == brand_id)
    if campaign_id is not None:
        stmt = stmt.where(Event.campaign_id == campaign_id)
    if event_status is not None:
        stmt = stmt.where(Event.status == event_status)
    if not include_inactive:
        stmt = stmt.where(Event.status != EventStatus.CANCELLED)
    if principal is not None and principal.brand_scope is not None:
        stmt = stmt.where(Event.brand_id.in_(principal.brand_scope))

    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Event.event_date, id_column=Event.id
    )

    counts: dict[uuid.UUID, int] = {}
    if rows:
        counted = await db.execute(
            select(EventSpeaker.event_id, func.count())
            .where(EventSpeaker.event_id.in_([r.id for r in rows]))
            .group_by(EventSpeaker.event_id)
        )
        counts = {eid: int(n) for eid, n in counted.all()}

    return Page(
        items=[
            _event_out(
                r,
                brand_name=r.brand.name if r.brand else None,
                speaker_count=counts.get(r.id, 0),
            )
            for r in rows
        ],
        next_cursor=cursor,
    )


@router.post(
    "/events",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event",
    dependencies=[Depends(require(Permission.EVENT_WRITE)), Depends(deny_vendor)],
)
async def create_event(db: TenantSession, payload: EventCreate) -> EventOut:
    brand = await crud.get_or_404(db, Brand, payload.brand_id, resource="brand")
    _assert_brand_visible(brand.id)
    if not brand.is_active:
        raise ValidationError(
            "That brand has been retired, so a new event cannot be created for it.",
            remediation="Reactivate the brand first, or choose another.",
        )
    row = await crud.create(
        db,
        Event,
        payload.model_dump(exclude_unset=True),
        resource="event",
        audit_fields=_EVENT_AUDIT,
        label=payload.code,
        actor_id=_actor_id(),
    )
    return _event_out(row, brand_name=brand.name, speaker_count=0)


@router.get(
    "/events/{event_id}",
    response_model=EventOut,
    summary="Get an event",
    dependencies=[Depends(require(Permission.EVENT_READ))],
)
async def get_event(db: ReadOnlySession, event_id: uuid.UUID) -> EventOut:
    row = await crud.get_or_404(
        db,
        Event,
        event_id,
        resource="event",
        options=[selectinload(Event.brand), selectinload(Event.speakers)],
    )
    _assert_brand_visible(row.brand_id)
    return _event_out(
        row,
        brand_name=row.brand.name if row.brand else None,
        speaker_count=len(row.speakers),
        include_speakers=True,
    )


@router.patch(
    "/events/{event_id}",
    response_model=EventOut,
    summary="Update an event",
    dependencies=[Depends(require(Permission.EVENT_WRITE)), Depends(deny_vendor)],
)
async def patch_event(db: TenantSession, event_id: uuid.UUID, payload: EventPatch) -> EventOut:
    row = await crud.get_or_404(
        db, Event, event_id, resource="event", options=[selectinload(Event.brand)]
    )
    _assert_brand_visible(row.brand_id)
    await crud.update(
        db,
        row,
        crud.patch_changes(
            payload,
            "name",
            "campaign_id",
            "event_date",
            "start_time",
            "end_time",
            "timezone",
            "format",
            "topic_code",
            "region_code",
            "venue_city",
            "venue_name",
            "speaker_tier",
            "planned_attendance",
            "status",
        ),
        resource="event",
        audit_fields=_EVENT_AUDIT,
        expected_version=payload.version,
        label=row.code,
        actor_id=_actor_id(),
    )
    return _event_out(row, brand_name=row.brand.name if row.brand else None)


@router.post(
    "/events/{event_id}/deactivate",
    response_model=Acknowledged,
    summary="Cancel an event",
    dependencies=[Depends(require(Permission.EVENT_WRITE)), Depends(deny_vendor)],
)
async def cancel_event(
    db: TenantSession, event_id: uuid.UUID, payload: DeactivateRequest
) -> Acknowledged:
    row = await crud.get_or_404(db, Event, event_id, resource="event")
    _assert_brand_visible(row.brand_id)
    await crud.update(
        db,
        row,
        {"status": EventStatus.CANCELLED},
        resource="event",
        audit_fields=_EVENT_AUDIT,
        label=row.code,
        actor_id=_actor_id(),
        reason=payload.reason,
    )
    return Acknowledged()


# ---------------------------------------------------------------------------
# Speakers (nested under events)
# ---------------------------------------------------------------------------


@router.get(
    "/events/{event_id}/speakers",
    response_model=list[EventSpeakerOut],
    summary="List speakers for an event",
    dependencies=[Depends(require(Permission.EVENT_READ))],
)
async def list_speakers(db: ReadOnlySession, event_id: uuid.UUID) -> list[EventSpeakerOut]:
    event = await crud.get_or_404(
        db, Event, event_id, resource="event", options=[selectinload(Event.speakers)]
    )
    _assert_brand_visible(event.brand_id)
    return [_speaker_out(s) for s in event.speakers]


@router.post(
    "/events/{event_id}/speakers",
    response_model=EventSpeakerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a speaker to an event",
    dependencies=[Depends(require(Permission.EVENT_WRITE)), Depends(deny_vendor)],
)
async def add_speaker(
    db: TenantSession, event_id: uuid.UUID, payload: EventSpeakerIn
) -> EventSpeakerOut:
    event = await crud.get_or_404(db, Event, event_id, resource="event")
    _assert_brand_visible(event.brand_id)
    if payload.hcp_id is None and payload.external_speaker_code is None:
        raise ValidationError(
            "Either an HCP id or an external speaker code must be provided.",
            remediation="Supply hcpId or externalSpeakerCode.",
        )
    row = EventSpeaker(
        event_id=event_id,
        hcp_id=payload.hcp_id,
        external_speaker_code=payload.external_speaker_code,
        tier=payload.tier,
        speaking_role=payload.speaking_role,
        honorarium_amount=payload.honorarium_amount,
        currency=payload.currency,
        created_by=_actor_id(),
    )
    db.add(row)
    await db.flush([row])
    await audit.record(
        db,
        AuditAction.RECORD_CREATED,
        resource_type="event_speaker",
        resource_id=row.id,
        status_code=201,
    )
    return _speaker_out(row)


@router.delete(
    "/events/{event_id}/speakers/{speaker_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a speaker from an event",
    dependencies=[Depends(require(Permission.EVENT_WRITE)), Depends(deny_vendor)],
)
async def remove_speaker(db: TenantSession, event_id: uuid.UUID, speaker_id: uuid.UUID) -> Response:
    speaker = (
        await db.execute(
            select(EventSpeaker).where(
                EventSpeaker.id == speaker_id, EventSpeaker.event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if speaker is None:
        raise NotFoundError("event_speaker", speaker_id)
    await audit.record(
        db,
        AuditAction.RECORD_DELETED,
        resource_type="event_speaker",
        resource_id=speaker.id,
        status_code=204,
    )
    await db.delete(speaker)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
