"""Dashboard response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardStats(BaseModel):
    """Top-level KPI overview."""

    total_brands: int = Field(serialization_alias="totalBrands")
    total_hcps: int = Field(serialization_alias="totalHcps")
    total_campaigns: int = Field(serialization_alias="totalCampaigns")
    total_events: int = Field(serialization_alias="totalEvents")
    total_spend: float = Field(serialization_alias="totalSpend")
    total_attendees: int = Field(serialization_alias="totalAttendees")
    engagement_rate: float = Field(serialization_alias="engagementRate")
    avg_roi: float | None = Field(default=None, serialization_alias="avgRoi")

    model_config = {"populate_by_name": True}


class MonthlyBrandSpend(BaseModel):
    month: str
    brand: str
    spend: float
    trx: int


class RoiTrendResponse(BaseModel):
    trend: list[MonthlyBrandSpend]

    model_config = {"populate_by_name": True}


class EngagementBucket(BaseModel):
    bucket: str
    count: int


class SpecialtyEngagement(BaseModel):
    specialty: str
    avg_events: float = Field(serialization_alias="avgEvents")


class RegionEngagement(BaseModel):
    region: str
    avg_events: float = Field(serialization_alias="avgEvents")


class EngagementResponse(BaseModel):
    buckets: list[EngagementBucket]
    by_specialty: list[SpecialtyEngagement] = Field(serialization_alias="bySpecialty")
    by_region: list[RegionEngagement] = Field(serialization_alias="byRegion")

    model_config = {"populate_by_name": True}


__all__ = [
    "DashboardStats",
    "EngagementBucket",
    "EngagementResponse",
    "MonthlyBrandSpend",
    "RegionEngagement",
    "RoiTrendResponse",
    "SpecialtyEngagement",
]
