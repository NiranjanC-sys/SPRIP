"""HCP (Healthcare Professional) schemas.

Professional-grain only. No names, phones, emails, addresses or ABHA identifiers - plan.md §15
prohibits ingesting them.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_api.schemas.master_data import Code, ShortText


class HcpCreate(Schema):
    master_hcp_id: str = Field(
        validation_alias="masterHcpId",
        min_length=1,
        max_length=80,
    )
    specialty_code: Code | None = Field(default=None, validation_alias="specialtyCode")
    region_code: Code | None = Field(default=None, validation_alias="regionCode")
    practice_type: ShortText | None = Field(default=None, validation_alias="practiceType")
    segment: ShortText | None = None
    city_code: Code | None = Field(default=None, validation_alias="cityCode")
    first_seen_on: date | None = Field(default=None, validation_alias="firstSeenOn")


class HcpPatch(Schema):
    specialty_code: Code | None = Field(default=None, validation_alias="specialtyCode")
    region_code: Code | None = Field(default=None, validation_alias="regionCode")
    practice_type: ShortText | None = Field(default=None, validation_alias="practiceType")
    segment: ShortText | None = None
    city_code: Code | None = Field(default=None, validation_alias="cityCode")
    version: int | None = None


class HcpOut(Schema):
    id: uuid.UUID
    master_hcp_id: str = Field(serialization_alias="masterHcpId")
    specialty_code: str | None = Field(default=None, serialization_alias="specialtyCode")
    region_code: str | None = Field(default=None, serialization_alias="regionCode")
    practice_type: str | None = Field(default=None, serialization_alias="practiceType")
    segment: str | None = None
    city_code: str | None = Field(default=None, serialization_alias="cityCode")
    is_active: bool = Field(serialization_alias="isActive")
    first_seen_on: date | None = Field(default=None, serialization_alias="firstSeenOn")
    audit: AuditStamp | None = None


__all__ = ["HcpCreate", "HcpOut", "HcpPatch"]
