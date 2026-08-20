"""Tenant management schemas for the platform console."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_core.enums import TenantStatus

Code = Annotated[
    str,
    StringConstraints(
        min_length=2, max_length=40, strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    ),
]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]


class TenantCreate(Schema):
    code: Code
    name: Name
    country: str = Field(default="IN", min_length=2, max_length=2)
    reporting_currency: str = Field(
        default="INR", alias="reportingCurrency", min_length=3, max_length=3
    )
    locale: str = Field(default="en-IN", max_length=10)
    timezone: str = Field(default="Asia/Kolkata", max_length=60)
    fiscal_year_start_month: int = Field(default=4, alias="fiscalYearStartMonth", ge=1, le=12)
    synthetic_mode: bool = Field(default=False, alias="syntheticMode")


class TenantPatch(Schema):
    name: Name | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    reporting_currency: str | None = Field(
        default=None, alias="reportingCurrency", min_length=3, max_length=3
    )
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=60)
    fiscal_year_start_month: int | None = Field(
        default=None, alias="fiscalYearStartMonth", ge=1, le=12
    )
    version: int


class TenantOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    status: TenantStatus
    country: str
    reporting_currency: str = Field(alias="reportingCurrency")
    locale: str
    timezone: str
    fiscal_year_start_month: int = Field(alias="fiscalYearStartMonth")
    synthetic_mode: bool = Field(alias="syntheticMode")
    data_retention_days: int = Field(alias="dataRetentionDays")
    user_count: int | None = Field(default=None, alias="userCount")
    suspended_at: datetime | None = Field(default=None, alias="suspendedAt")
    suspended_reason: str | None = Field(default=None, alias="suspendedReason")
    audit: AuditStamp


class SuspendRequest(Schema):
    reason: str = Field(min_length=1, max_length=500)


__all__ = [
    "SuspendRequest",
    "TenantCreate",
    "TenantOut",
    "TenantPatch",
]
