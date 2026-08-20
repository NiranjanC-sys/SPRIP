"""Forecast schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field

from speaker_roi_api.schemas.common import Schema


class ForecastOut(Schema):
    id: uuid.UUID
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    period_start: date | None = Field(default=None, serialization_alias="periodStart")
    period_end: date | None = Field(default=None, serialization_alias="periodEnd")
    predicted_nrx: float | None = Field(default=None, serialization_alias="predictedNrx")
    predicted_revenue: float | None = Field(default=None, serialization_alias="predictedRevenue")
    confidence_low: float | None = Field(default=None, serialization_alias="confidenceLow")
    confidence_high: float | None = Field(default=None, serialization_alias="confidenceHigh")
    model_version: str | None = Field(default=None, serialization_alias="modelVersion")
    created_at: datetime | None = Field(default=None, serialization_alias="createdAt")


class ForecastCreate(Schema):
    brand_id: uuid.UUID = Field(validation_alias="brandId")
    horizon_months: int = Field(default=12, validation_alias="horizonMonths", ge=1, le=60)


class ForecastTaskOut(Schema):
    task_id: str = Field(serialization_alias="taskId")
    status: str


__all__ = [
    "ForecastCreate",
    "ForecastOut",
    "ForecastTaskOut",
]
