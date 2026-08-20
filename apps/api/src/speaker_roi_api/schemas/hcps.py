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


class RxHistoryItem(Schema):
    month: str
    nrx: float
    trx: float
    brand_id: str = Field(serialization_alias="brandId")


class AttendedEventItem(Schema):
    id: uuid.UUID
    name: str | None = None
    date: str | None = None
    status: str | None = None
    role: str | None = None


class HcpDetailOut(HcpOut):
    rx_history: list[RxHistoryItem] = Field(default_factory=list, serialization_alias="rxHistory")
    events_attended: list[AttendedEventItem] = Field(default_factory=list, serialization_alias="eventsAttended")


__all__ = ["HcpCreate", "HcpDetailOut", "HcpOut", "HcpPatch"]
