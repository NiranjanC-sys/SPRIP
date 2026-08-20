"""Optimizer / what-if scenario schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema


class ScenarioCreate(Schema):
    name: str = Field(min_length=1, max_length=200)
    brand_id: uuid.UUID | None = Field(default=None, validation_alias="brandId")
    budget_change_pct: float = Field(default=0, validation_alias="budgetChangePct")
    event_count_change: int = Field(default=0, validation_alias="eventCountChange")


class ScenarioOut(Schema):
    id: uuid.UUID
    name: str
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    budget_change_pct: float = Field(default=0, serialization_alias="budgetChangePct")
    event_count_change: int = Field(default=0, serialization_alias="eventCountChange")
    projected_roi: float | None = Field(default=None, serialization_alias="projectedRoi")
    projected_nrx: float | None = Field(default=None, serialization_alias="projectedNrx")
    status: str
    audit: AuditStamp | None = None


__all__ = [
    "ScenarioCreate",
    "ScenarioOut",
]
