"""Ingestion, upload session and data version schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field

from speaker_roi_api.schemas.common import Schema


class UploadSessionCreate(Schema):
    dataset_type: str = Field(validation_alias="datasetType", max_length=60)
    file_name: str = Field(validation_alias="fileName", max_length=500)


class UploadSessionOut(Schema):
    id: uuid.UUID
    dataset_type: str = Field(serialization_alias="datasetType")
    file_name: str = Field(serialization_alias="fileName")
    file_size_bytes: int | None = Field(default=None, serialization_alias="fileSizeBytes")
    status: str
    row_count: int | None = Field(default=None, serialization_alias="rowCount")
    error_count: int | None = Field(default=None, serialization_alias="errorCount")
    created_at: datetime | None = Field(default=None, serialization_alias="createdAt")
    created_by: uuid.UUID | None = Field(default=None, serialization_alias="createdBy")


class ValidationIssueOut(Schema):
    id: uuid.UUID
    session_id: uuid.UUID = Field(serialization_alias="sessionId")
    row_number: int | None = Field(default=None, serialization_alias="rowNumber")
    field_name: str | None = Field(default=None, serialization_alias="fieldName")
    rule_code: str = Field(serialization_alias="ruleCode")
    severity: str
    message: str | None = None


class DataVersionOut(Schema):
    id: uuid.UUID
    dataset_type: str = Field(serialization_alias="datasetType")
    version_number: int = Field(serialization_alias="versionNumber")
    session_id: uuid.UUID | None = Field(default=None, serialization_alias="sessionId")
    effective_date: date | None = Field(default=None, serialization_alias="effectiveDate")
    row_count: int | None = Field(default=None, serialization_alias="rowCount")
    status: str
    published_at: datetime | None = Field(default=None, serialization_alias="publishedAt")
    published_by: uuid.UUID | None = Field(default=None, serialization_alias="publishedBy")


class AuditEventOut(Schema):
    id: uuid.UUID
    action: str
    resource_type: str = Field(serialization_alias="resourceType")
    resource_id: uuid.UUID | None = Field(default=None, serialization_alias="resourceId")
    actor_id: uuid.UUID | None = Field(default=None, serialization_alias="actorId")
    actor_email: str | None = Field(default=None, serialization_alias="actorEmail")
    tenant_id: uuid.UUID | None = Field(default=None, serialization_alias="tenantId")
    status_code: int | None = Field(default=None, serialization_alias="statusCode")
    detail: dict | None = None
    created_at: datetime | None = Field(default=None, serialization_alias="createdAt")
    ip_address: str | None = Field(default=None, serialization_alias="ipAddress")


class UploadFileResponse(Schema):
    session_id: uuid.UUID = Field(serialization_alias="sessionId")
    task_id: str = Field(serialization_alias="taskId")
    status: str


__all__ = [
    "AuditEventOut",
    "DataVersionOut",
    "UploadFileResponse",
    "UploadSessionCreate",
    "UploadSessionOut",
    "ValidationIssueOut",
]
