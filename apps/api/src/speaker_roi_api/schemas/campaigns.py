"""Campaign schemas."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_api.schemas.master_data import Code, Name
from speaker_roi_core.enums import CampaignStatus


class CampaignCreate(Schema):
    code: Code
    name: Name
    brand_id: uuid.UUID = Field(validation_alias="brandId")
    objective: str | None = Field(default=None, max_length=200)
    topic_code: Code | None = Field(default=None, validation_alias="topicCode")
    start_date: date = Field(validation_alias="startDate")
    end_date: date | None = Field(default=None, validation_alias="endDate")
    status: CampaignStatus = CampaignStatus.DRAFT
    owner_user_id: uuid.UUID | None = Field(default=None, validation_alias="ownerUserId")
    planned_budget: float | None = Field(default=None, validation_alias="plannedBudget", ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class CampaignPatch(Schema):
    name: Name | None = None
    objective: str | None = Field(default=None, max_length=200)
    topic_code: Code | None = Field(default=None, validation_alias="topicCode")
    start_date: date | None = Field(default=None, validation_alias="startDate")
    end_date: date | None = Field(default=None, validation_alias="endDate")
    status: CampaignStatus | None = None
    owner_user_id: uuid.UUID | None = Field(default=None, validation_alias="ownerUserId")
    planned_budget: float | None = Field(default=None, validation_alias="plannedBudget", ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    version: int | None = None


class CampaignOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    brand_id: uuid.UUID = Field(serialization_alias="brandId")
    brand_name: str | None = Field(default=None, serialization_alias="brandName")
    objective: str | None = None
    topic_code: str | None = Field(default=None, serialization_alias="topicCode")
    start_date: date = Field(serialization_alias="startDate")
    end_date: date | None = Field(default=None, serialization_alias="endDate")
    status: str
    owner_user_id: uuid.UUID | None = Field(default=None, serialization_alias="ownerUserId")
    planned_budget: float | None = Field(default=None, serialization_alias="plannedBudget")
    currency: str | None = None
    event_count: int | None = Field(default=None, serialization_alias="eventCount")
    is_active: bool = Field(default=True, serialization_alias="isActive")
    audit: AuditStamp | None = None


class CampaignEventItem(Schema):
    id: uuid.UUID
    name: str | None = None
    event_date: date = Field(serialization_alias="eventDate")
    status: str
    format: str
    impact_grade: str | None = Field(default=None, serialization_alias="impactGrade")
    incremental_nrx: float | None = Field(default=None, serialization_alias="incrementalNrx")


class CampaignDetailOut(CampaignOut):
    events: list[CampaignEventItem] = Field(default_factory=list)
    total_spend: float | None = Field(default=None, serialization_alias="totalSpend")
    total_incremental_nrx: float | None = Field(default=None, serialization_alias="totalIncrementalNrx")
    total_net_roi: float | None = Field(default=None, serialization_alias="totalNetRoi")
    avg_bcr: float | None = Field(default=None, serialization_alias="avgBcr")
    evidence_summary: str | None = Field(default=None, serialization_alias="evidenceSummary")


__all__ = [
    "CampaignCreate",
    "CampaignDetailOut",
    "CampaignEventItem",
    "CampaignOut",
    "CampaignPatch",
]
