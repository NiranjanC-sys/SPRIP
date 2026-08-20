"""Async export generation and status polling."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from speaker_roi_api.deps import ReadOnlySession, TenantSession, require
from speaker_roi_api.schemas.exports import ExportRequest, ExportStatusOut
from speaker_roi_api.security.rbac import Permission

router = APIRouter(tags=["Exports"])


@router.post(
    "/exports",
    response_model=ExportStatusOut,
    status_code=202,
    summary="Trigger async export generation",
    dependencies=[Depends(require(Permission.EXPORT_CREATE))],
)
async def create_export(db: TenantSession, payload: ExportRequest) -> ExportStatusOut:
    # Celery integration point: when the worker package is available on the API's
    # Python path, replace the placeholder below with:
    #   result = celery_app.send_task(
    #       "exports.generate_export",
    #       args=[payload.export_type, payload.filters],
    #   )
    #   task_id = result.id
    # For now, return a placeholder acknowledging the request.
    task_id = str(uuid.uuid4())
    return ExportStatusOut(task_id=task_id, status="QUEUED", download_url=None, expires_at=None)


@router.get(
    "/exports/{task_id}/status",
    response_model=ExportStatusOut,
    summary="Check export task status",
    dependencies=[Depends(require(Permission.EXPORT_READ))],
)
async def get_export_status(db: ReadOnlySession, task_id: str) -> ExportStatusOut:
    # Celery integration point: when the worker package is available on the API's
    # Python path, replace the placeholder below with:
    #   from celery.result import AsyncResult
    #   result = AsyncResult(task_id)
    #   status = result.state
    #   download_url = result.result.get("download_url") if result.ready() else None
    #   expires_at = result.result.get("expires_at") if result.ready() else None
    # For now, return PENDING as a placeholder.
    return ExportStatusOut(
        task_id=task_id, status="PENDING", download_url=None, expires_at=None
    )


__all__ = ["router"]
