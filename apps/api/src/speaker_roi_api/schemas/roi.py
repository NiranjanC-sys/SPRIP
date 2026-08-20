"""ROI result schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema


class RoiResultOut(Schema):
    id: uuid.UUID
    run_id: uuid.UUID = Field(serialization_alias="runId")
    level: str
    event_id: uuid.UUID | None = Field(default=None, serialization_alias="eventId")
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    incremental_nrx: float | None = Field(default=None, serialization_alias="incrementalNrx")
    gross_contribution: float | None = Field(default=None, serialization_alias="grossContribution")
    total_cost: float = Field(serialization_alias="totalCost")
    net_roi: float | None = Field(default=None, serialization_alias="netRoi")
    benefit_cost_ratio: float | None = Field(default=None, serialization_alias="benefitCostRatio")
    evidence_grade: str = Field(serialization_alias="evidenceGrade")
    currency: str
    audit: AuditStamp | None = None


class BrandRoiSummary(Schema):
    brand_id: uuid.UUID = Field(serialization_alias="brandId")
    brand_name: str | None = Field(default=None, serialization_alias="brandName")
    total_events: int = Field(serialization_alias="totalEvents")
    avg_bcr: float | None = Field(default=None, serialization_alias="avgBcr")
    total_spend: float = Field(serialization_alias="totalSpend")
    net_roi: float | None = Field(default=None, serialization_alias="netRoi")


class RoiSummaryOut(Schema):
    brands: list[BrandRoiSummary]
    portfolio_bcr: float | None = Field(default=None, serialization_alias="portfolioBcr")
    total_spend: float = Field(serialization_alias="totalSpend")


__all__ = [
    "BrandRoiSummary",
    "RoiResultOut",
    "RoiSummaryOut",
]
