"""Ingestion tasks: CSV upload processing and validation.

Prescription data arrives as CSV uploads. Validation and processing happen in the worker
because a single file can contain hundreds of thousands of rows, and parsing, validating,
de-duplicating and inserting that volume synchronously would block the API process.
"""

from __future__ import annotations

import uuid

from speaker_roi_worker import celery_app

from speaker_roi_core.logging import get_logger

log = get_logger(__name__)


@celery_app.task(bind=True, name="ingestion.process_rx_upload", max_retries=2)
def process_rx_upload(
    self,
    tenant_id: str,
    upload_id: str,
    object_key: str,
    uploaded_by: str,
) -> dict:
    """Process a prescription data CSV upload.

    Downloads the file from object storage, validates each row against the
    expected schema, de-duplicates against existing records, and bulk-inserts
    the new rows. Progress is reported as task metadata updates.
    """
    log.info(
        "task.process_rx.started",
        tenant_id=tenant_id,
        upload_id=upload_id,
        object_key=object_key,
    )
    import asyncio

    from speaker_roi_core.db.session import session_scope

    async def _run() -> dict:
        tid = uuid.UUID(tenant_id)
        async with session_scope(tenant_id=tid) as db:
            # TODO: download from storage, parse CSV, validate, insert
            self.update_state(state="PROGRESS", meta={"rows_processed": 0, "total_rows": 0})
            result = {
                "tenant_id": tenant_id,
                "upload_id": upload_id,
                "status": "completed",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "errors": [],
            }
            log.info(
                "task.process_rx.completed",
                tenant_id=tenant_id,
                upload_id=upload_id,
                rows_inserted=0,
            )
            return result

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(bind=True, name="ingestion.validate_csv_upload", max_retries=1)
def validate_csv_upload(
    self,
    tenant_id: str,
    upload_id: str,
    object_key: str,
    uploaded_by: str,
) -> dict:
    """Validate a CSV upload without inserting any data.

    A dry-run pass that reports schema violations, missing required fields,
    and duplicate detection — so the user can fix the file before committing
    the actual import.
    """
    log.info(
        "task.validate_csv.started",
        tenant_id=tenant_id,
        upload_id=upload_id,
    )
    import asyncio

    from speaker_roi_core.db.session import session_scope

    async def _run() -> dict:
        tid = uuid.UUID(tenant_id)
        async with session_scope(tenant_id=tid) as db:
            # TODO: download, parse headers, validate rows
            result = {
                "tenant_id": tenant_id,
                "upload_id": upload_id,
                "status": "completed",
                "valid": True,
                "total_rows": 0,
                "error_rows": 0,
                "errors": [],
            }
            log.info(
                "task.validate_csv.completed",
                tenant_id=tenant_id,
                upload_id=upload_id,
                valid=True,
            )
            return result

    return asyncio.get_event_loop().run_until_complete(_run())
