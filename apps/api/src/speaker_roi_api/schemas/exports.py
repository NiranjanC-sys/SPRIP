"""Export schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from speaker_roi_api.schemas.common import Schema


class ExportType(StrEnum):
    PORTFOLIO_REPORT = "portfolio_report"
    EVENT_SUMMARY = "event_summary"
    ROI_ANALYSIS = "roi_analysis"


class ExportRequest(Schema):
    export_type: ExportType = Field(validation_alias="exportType")
    filters: dict | None = None


class ExportStatusOut(Schema):
    task_id: str = Field(serialization_alias="taskId")
    status: str
    download_url: str | None = Field(default=None, serialization_alias="downloadUrl")
    expires_at: datetime | None = Field(default=None, serialization_alias="expiresAt")


__all__ = [
    "ExportRequest",
    "ExportStatusOut",
    "ExportType",
]
