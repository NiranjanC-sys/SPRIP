"""Finance, cost and ROI schemas."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_api.schemas.master_data import Code


class EventCostCreate(Schema):
    event_id: uuid.UUID = Field(validation_alias="eventId")
    category_code: Code = Field(validation_alias="categoryCode")
    description: str | None = Field(default=None, max_length=200)
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    vendor_id: uuid.UUID | None = Field(default=None, validation_alias="vendorId")


class EventCostPatch(Schema):
    category_code: Code | None = Field(default=None, validation_alias="categoryCode")
    description: str | None = Field(default=None, max_length=200)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    version: int | None = None


class EventCostOut(Schema):
    id: uuid.UUID
    event_id: uuid.UUID = Field(serialization_alias="eventId")
    category_code: str = Field(serialization_alias="categoryCode")
    description: str | None = None
    amount: float
    currency: str
    vendor_id: uuid.UUID | None = Field(default=None, serialization_alias="vendorId")
    is_active: bool = Field(serialization_alias="isActive")
    audit: AuditStamp | None = None


class FinanceAssumptionCreate(Schema):
    finance_version_id: uuid.UUID = Field(validation_alias="financeVersionId")
    brand_id: uuid.UUID = Field(validation_alias="brandId")
    scenario: str = "BASE"
    contribution_per_nrx: float = Field(validation_alias="contributionPerNrx", ge=0)
    currency: str = Field(min_length=3, max_length=3)
    effective_from: date = Field(validation_alias="effectiveFrom")
    effective_to: date | None = Field(default=None, validation_alias="effectiveTo")
    persistence_months: int | None = Field(default=None, validation_alias="persistenceMonths", ge=0)
    note: str | None = Field(default=None, max_length=500)


class FinanceAssumptionPatch(Schema):
    contribution_per_nrx: float | None = Field(
        default=None, validation_alias="contributionPerNrx", ge=0
    )
    effective_to: date | None = Field(default=None, validation_alias="effectiveTo")
    persistence_months: int | None = Field(default=None, validation_alias="persistenceMonths", ge=0)
    note: str | None = Field(default=None, max_length=500)
    version: int | None = None


class FinanceAssumptionOut(Schema):
    id: uuid.UUID
    finance_version_id: uuid.UUID = Field(serialization_alias="financeVersionId")
    brand_id: uuid.UUID = Field(serialization_alias="brandId")
    scenario: str
    contribution_per_nrx: float = Field(serialization_alias="contributionPerNrx")
    currency: str
    effective_from: date = Field(serialization_alias="effectiveFrom")
    effective_to: date | None = Field(default=None, serialization_alias="effectiveTo")
    persistence_months: int | None = Field(default=None, serialization_alias="persistenceMonths")
    note: str | None = None
    audit: AuditStamp | None = None


class RoiResultOut(Schema):
    id: uuid.UUID
    run_id: uuid.UUID = Field(serialization_alias="runId")
    level: str
    event_id: uuid.UUID | None = Field(default=None, serialization_alias="eventId")
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    finance_version_id: uuid.UUID = Field(serialization_alias="financeVersionId")
    incremental_nrx: float | None = Field(default=None, serialization_alias="incrementalNrx")
    gross_contribution: float | None = Field(default=None, serialization_alias="grossContribution")
    total_cost: float = Field(serialization_alias="totalCost")
    net_roi: float | None = Field(default=None, serialization_alias="netRoi")
    benefit_cost_ratio: float | None = Field(default=None, serialization_alias="benefitCostRatio")
    currency: str
    evidence_status: str = Field(serialization_alias="evidenceStatus")
    evidence_grade: str = Field(serialization_alias="evidenceGrade")
    publication_state: str = Field(serialization_alias="publicationState")
    audit: AuditStamp | None = None


__all__ = [
    "EventCostCreate",
    "EventCostOut",
    "EventCostPatch",
    "FinanceAssumptionCreate",
    "FinanceAssumptionOut",
    "FinanceAssumptionPatch",
    "RoiResultOut",
]
