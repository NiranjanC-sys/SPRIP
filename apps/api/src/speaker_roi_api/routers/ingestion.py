"""Data ingestion: upload sessions, validation issues and data versions."""

from __future__ import annotations

import io
import uuid
from typing import Annotated

import boto3
from celery import Celery
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, require
from speaker_roi_api.schemas.common import Acknowledged, Page
from speaker_roi_api.schemas.ingestion import (
    DataVersionOut,
    UploadFileResponse,
    UploadSessionCreate,
    UploadSessionOut,
    ValidationIssueOut,
)
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import audit, crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.enums import AuditAction
from speaker_roi_core.models.ingestion import DataVersion, UploadIssue, UploadSession

# ---------------------------------------------------------------------------
# MinIO (S3-compatible) client
# ---------------------------------------------------------------------------
_MINIO_ENDPOINT = "http://127.0.0.1:9100"
_MINIO_BUCKET = "speaker-roi-uploads"

_s3 = boto3.client(
    "s3",
    endpoint_url=_MINIO_ENDPOINT,
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
    region_name="us-east-1",
)

# ---------------------------------------------------------------------------
# Celery client (broker-only, no worker import required)
# ---------------------------------------------------------------------------
_celery = Celery(broker="redis://127.0.0.1:63799/0")

# ---------------------------------------------------------------------------
# Upload safety constants
# ---------------------------------------------------------------------------
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
_BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif", ".vbs",
    ".js", ".wsf", ".ps1", ".sh", ".dll", ".so", ".dylib",
}
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

router = APIRouter(tags=["Ingestion"])


def _actor_id() -> uuid.UUID | None:
    principal = current_principal()
    return principal.user_id if principal else None


def _session_out(row: UploadSession) -> UploadSessionOut:
    return UploadSessionOut(
        id=row.id,
        dataset_type=str(row.dataset_type),
        file_name=getattr(row, "file_name", None) or "",
        file_size_bytes=None,
        status=str(row.status),
        row_count=row.row_count_total,
        error_count=row.error_count,
        created_at=row.created_at,
        created_by=row.created_by,
    )


def _issue_out(row: UploadIssue) -> ValidationIssueOut:
    return ValidationIssueOut(
        id=row.id,
        session_id=row.upload_session_id,
        row_number=row.source_row_number,
        field_name=row.column_name,
        rule_code=row.code,
        severity=str(row.severity),
        message=row.message,
    )


def _version_out(row: DataVersion) -> DataVersionOut:
    return DataVersionOut(
        id=row.id,
        dataset_type=str(row.dataset_type),
        version_number=row.version_number,
        session_id=row.upload_session_id,
        effective_date=row.period_start,
        row_count=row.row_count,
        status=str(row.status),
        published_at=row.published_at,
        published_by=row.published_by,
    )


@router.get(
    "/uploads/sessions",
    response_model=Page[UploadSessionOut],
    summary="List upload sessions",
    dependencies=[Depends(require(Permission.UPLOAD_READ))],
)
async def list_sessions(
    db: ReadOnlySession,
    page: PageParams,
    dataset_type: Annotated[str | None, Query(alias="datasetType")] = None,
    upload_status: Annotated[str | None, Query(alias="status")] = None,
) -> Page[UploadSessionOut]:
    stmt = select(UploadSession)
    if dataset_type is not None:
        stmt = stmt.where(UploadSession.dataset_type == dataset_type)
    if upload_status is not None:
        stmt = stmt.where(UploadSession.status == upload_status)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=UploadSession.created_at, id_column=UploadSession.id
    )
    return Page(items=[_session_out(r) for r in rows], next_cursor=cursor)


@router.get(
    "/uploads/sessions/{session_id}",
    response_model=UploadSessionOut,
    summary="Get an upload session",
    dependencies=[Depends(require(Permission.UPLOAD_READ))],
)
async def get_session(db: ReadOnlySession, session_id: uuid.UUID) -> UploadSessionOut:
    row = await crud.get_or_404(db, UploadSession, session_id, resource="upload_session")
    return _session_out(row)


@router.post(
    "/uploads/files",
    response_model=UploadFileResponse,
    status_code=202,
    summary="Upload a CSV file for processing",
    dependencies=[Depends(require(Permission.UPLOAD_WRITE))],
)
async def upload_file(
    db: TenantSession,
    file: UploadFile = File(...),
    dataset_type: str = Form("rx_monthly"),
) -> UploadFileResponse:
    # --- extension check ---------------------------------------------------
    filename = file.filename or "upload.csv"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _BLOCKED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Executable file types are not allowed.")
    if ext != ".csv":
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    # --- size check --------------------------------------------------------
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    # --- CSV formula injection check ---------------------------------------
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 text.")

    for line_no, line in enumerate(text.splitlines()[:5000], start=1):
        for cell in line.split(","):
            stripped = cell.strip().strip('"').strip("'")
            if stripped and stripped[0] in _FORMULA_PREFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Potential formula injection detected at row {line_no}. "
                    f"Cells must not start with {stripped[0]!r}.",
                )

    # --- upload to MinIO ---------------------------------------------------
    principal = current_principal()
    tenant_id = str(principal.tenant_id) if principal else "unknown"
    session_id = uuid.uuid4()
    object_key = f"{tenant_id}/{session_id}/{filename}"

    _s3.upload_fileobj(
        io.BytesIO(contents),
        _MINIO_BUCKET,
        object_key,
        ExtraArgs={"ContentType": "text/csv"},
    )

    # --- create DB session record ------------------------------------------
    actor_id = _actor_id()
    row = await crud.create(
        db,
        UploadSession,
        {
            "id": session_id,
            "dataset_type": dataset_type,
            "file_name": filename,
            "contract_version": "1.0",
        },
        resource="upload_session",
        audit_fields=("dataset_type", "status"),
        label=dataset_type,
        actor_id=actor_id,
    )

    # --- dispatch Celery task ----------------------------------------------
    result = _celery.send_task(
        "ingestion.process_rx_upload",
        args=[tenant_id, str(session_id), object_key, str(actor_id) if actor_id else None],
    )

    return UploadFileResponse(
        session_id=row.id,
        task_id=result.id,
        status="processing",
    )


@router.post(
    "/uploads/sessions",
    response_model=UploadSessionOut,
    status_code=201,
    summary="Create an upload session",
    dependencies=[Depends(require(Permission.UPLOAD_WRITE))],
)
async def create_session(db: TenantSession, payload: UploadSessionCreate) -> UploadSessionOut:
    row = await crud.create(
        db,
        UploadSession,
        {
            "dataset_type": payload.dataset_type,
            "contract_version": "1.0",
        },
        resource="upload_session",
        audit_fields=("dataset_type", "status"),
        label=payload.dataset_type,
        actor_id=_actor_id(),
    )
    return _session_out(row)


@router.get(
    "/uploads/sessions/{session_id}/issues",
    response_model=Page[ValidationIssueOut],
    summary="List validation issues for a session",
    dependencies=[Depends(require(Permission.UPLOAD_READ))],
)
async def list_issues(
    db: ReadOnlySession, session_id: uuid.UUID, page: PageParams
) -> Page[ValidationIssueOut]:
    stmt = select(UploadIssue).where(UploadIssue.upload_session_id == session_id)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=UploadIssue.source_row_number, id_column=UploadIssue.id
    )
    return Page(items=[_issue_out(r) for r in rows], next_cursor=cursor)


@router.get(
    "/data-versions",
    response_model=Page[DataVersionOut],
    summary="List data versions",
    dependencies=[Depends(require(Permission.UPLOAD_READ))],
)
async def list_data_versions(
    db: ReadOnlySession,
    page: PageParams,
    dataset_type: Annotated[str | None, Query(alias="datasetType")] = None,
) -> Page[DataVersionOut]:
    stmt = select(DataVersion)
    if dataset_type is not None:
        stmt = stmt.where(DataVersion.dataset_type == dataset_type)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=DataVersion.version_number, id_column=DataVersion.id
    )
    return Page(items=[_version_out(r) for r in rows], next_cursor=cursor)


@router.post(
    "/data-versions/{version_id}/publish",
    response_model=Acknowledged,
    summary="Publish a data version",
    dependencies=[Depends(require(Permission.DATA_VERSION_PUBLISH))],
)
async def publish_data_version(db: TenantSession, version_id: uuid.UUID) -> Acknowledged:
    from datetime import UTC, datetime

    row = await crud.get_or_404(db, DataVersion, version_id, resource="data_version")
    row.published_at = datetime.now(UTC)
    row.published_by = _actor_id()
    row.status = "PUBLISHED"
    await db.flush()
    await audit.record(
        db,
        AuditAction.STATUS_CHANGED,
        resource_type="data_version",
        resource_id=row.id,
        status_code=200,
    )
    return Acknowledged()


__all__ = ["router"]
