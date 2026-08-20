"""Event and speaker-program schemas."""

from __future__ import annotations

import uuid
from datetime import date, time

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_api.schemas.master_data import Code, Name, ShortText
from speaker_roi_core.enums import EventFormat, EventStatus


class EventSpeakerIn(Schema):
    hcp_id: uuid.UUID | None = Field(default=None, validation_alias="hcpId")
    external_speaker_code: str | None = Field(
        default=None, validation_alias="externalSpeakerCode", max_length=80
    )
    tier: ShortText | None = None
    speaking_role: ShortText | None = Field(default=None, validation_alias="speakingRole")
    honorarium_amount: float | None = Field(default=None, validation_alias="honorariumAmount")
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class EventSpeakerOut(Schema):
    id: uuid.UUID
    event_id: uuid.UUID = Field(serialization_alias="eventId")
    hcp_id: uuid.UUID | None = Field(default=None, serialization_alias="hcpId")
    external_speaker_code: str | None = Field(
        default=None, serialization_alias="externalSpeakerCode"
    )
    tier: str | None = None
    speaking_role: str | None = Field(default=None, serialization_alias="speakingRole")
    honorarium_amount: float | None = Field(default=None, serialization_alias="honorariumAmount")
    currency: str | None = None


class EventCreate(Schema):
    code: Code
    name: Name | None = None
    brand_id: uuid.UUID = Field(validation_alias="brandId")
    campaign_id: uuid.UUID | None = Field(default=None, validation_alias="campaignId")
    event_date: date = Field(validation_alias="eventDate")
    start_time: time | None = Field(default=None, validation_alias="startTime")
    end_time: time | None = Field(default=None, validation_alias="endTime")
    timezone: str | None = Field(default=None, max_length=60)
    format: EventFormat
    topic_code: Code | None = Field(default=None, validation_alias="topicCode")
    region_code: Code | None = Field(default=None, validation_alias="regionCode")
    venue_city: str | None = Field(default=None, validation_alias="venueCity", max_length=120)
    venue_name: str | None = Field(default=None, validation_alias="venueName", max_length=200)
    speaker_tier: ShortText | None = Field(default=None, validation_alias="speakerTier")
    planned_attendance: int | None = Field(default=None, validation_alias="plannedAttendance", ge=0)
    status: EventStatus = EventStatus.PROPOSED


class EventPatch(Schema):
    name: Name | None = None
    campaign_id: uuid.UUID | None = Field(default=None, validation_alias="campaignId")
    event_date: date | None = Field(default=None, validation_alias="eventDate")
    start_time: time | None = Field(default=None, validation_alias="startTime")
    end_time: time | None = Field(default=None, validation_alias="endTime")
    timezone: str | None = Field(default=None, max_length=60)
    format: EventFormat | None = None
    topic_code: Code | None = Field(default=None, validation_alias="topicCode")
    region_code: Code | None = Field(default=None, validation_alias="regionCode")
    venue_city: str | None = Field(default=None, validation_alias="venueCity", max_length=120)
    venue_name: str | None = Field(default=None, validation_alias="venueName", max_length=200)
    speaker_tier: ShortText | None = Field(default=None, validation_alias="speakerTier")
    planned_attendance: int | None = Field(default=None, validation_alias="plannedAttendance", ge=0)
    status: EventStatus | None = None
    version: int | None = None


class EventOut(Schema):
    id: uuid.UUID
    code: str
    name: str | None = None
    brand_id: uuid.UUID = Field(serialization_alias="brandId")
    brand_name: str | None = Field(default=None, serialization_alias="brandName")
    campaign_id: uuid.UUID | None = Field(default=None, serialization_alias="campaignId")
    event_date: date = Field(serialization_alias="eventDate")
    start_time: time | None = Field(default=None, serialization_alias="startTime")
    end_time: time | None = Field(default=None, serialization_alias="endTime")
    timezone: str | None = None
    format: str
    topic_code: str | None = Field(default=None, serialization_alias="topicCode")
    region_code: str | None = Field(default=None, serialization_alias="regionCode")
    venue_city: str | None = Field(default=None, serialization_alias="venueCity")
    venue_name: str | None = Field(default=None, serialization_alias="venueName")
    speaker_tier: str | None = Field(default=None, serialization_alias="speakerTier")
    planned_attendance: int | None = Field(default=None, serialization_alias="plannedAttendance")
    status: str
    workflow_status: str = Field(serialization_alias="workflowStatus")
    measurement_eligible: bool = Field(serialization_alias="measurementEligible")
    exclusion_reason: str | None = Field(default=None, serialization_alias="exclusionReason")
    is_active: bool = Field(default=True, serialization_alias="isActive")
    speaker_count: int | None = Field(default=None, serialization_alias="speakerCount")
    speakers: list[EventSpeakerOut] | None = None
    audit: AuditStamp | None = None


class EventCostItem(Schema):
    category: str
    amount: float


class EventImpactSummary(Schema):
    incremental_value: float | None = Field(
        default=None, serialization_alias="incrementalValue"
    )
    p_value: float | None = Field(default=None, serialization_alias="pValue")
    grade: str | None = None
    confidence_level: float | None = Field(
        default=None, serialization_alias="confidenceLevel"
    )


class EventDetailOut(EventOut):
    attendance_count: int | None = Field(
        default=None, serialization_alias="attendanceCount"
    )
    total_cost: float | None = Field(default=None, serialization_alias="totalCost")
    cost_breakdown: list[EventCostItem] = Field(
        default_factory=list, serialization_alias="costBreakdown"
    )
    impact: EventImpactSummary | None = None


__all__ = [
    "EventCostItem",
    "EventCreate",
    "EventDetailOut",
    "EventImpactSummary",
    "EventOut",
    "EventPatch",
    "EventSpeakerIn",
    "EventSpeakerOut",
]
