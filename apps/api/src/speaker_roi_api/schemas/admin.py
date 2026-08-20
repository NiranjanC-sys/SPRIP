"""Admin schemas."""

from __future__ import annotations

import uuid

from pydantic import Field

from speaker_roi_api.schemas.common import Schema


class SystemStatsOut(Schema):
    tenant_count: int = Field(serialization_alias="tenantCount")
    user_count: int = Field(serialization_alias="userCount")
    total_events: int = Field(serialization_alias="totalEvents")


class TenantUsageOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    status: str
    user_count: int = Field(serialization_alias="userCount")
    event_count: int = Field(serialization_alias="eventCount")


class TenantToggleOut(Schema):
    id: uuid.UUID
    status: str


__all__ = [
    "SystemStatsOut",
    "TenantToggleOut",
    "TenantUsageOut",
]
