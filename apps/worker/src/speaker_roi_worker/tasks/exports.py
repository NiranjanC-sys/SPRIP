"""Export tasks: report generation and cleanup.

Exports are generated asynchronously because building a full portfolio report can
require reading every event, prescription and finance record in a tenant. The result
is written to object storage and the user is given a short-lived download URL.
"""

from __future__ import annotations

import uuid

from speaker_roi_worker import celery_app

from speaker_roi_core.logging import get_logger

log = get_logger(__name__)


@celery_app.task(bind=True, name="exports.generate_export", max_retries=2)
def generate_export(
    self,
    tenant_id: str,
    export_type: str,
    filters: dict | None = None,
    requested_by: str | None = None,
) -> dict:
    """Generate an export file and upload it to object storage.

    Supported export types: portfolio_report, event_summary, roi_analysis,
    prescription_data, finance_report.
    """
    log.info(
        "task.generate_export.started",
        tenant_id=tenant_id,
        export_type=export_type,
    )
    import asyncio

    from speaker_roi_core.db.session import session_scope

    async def _run() -> dict:
        tid = uuid.UUID(tenant_id)
        async with session_scope(tenant_id=tid) as db:
            # TODO: query data, build report, upload to storage
            self.update_state(state="PROGRESS", meta={"stage": "querying"})
            result = {
                "tenant_id": tenant_id,
                "export_type": export_type,
                "status": "completed",
                "object_key": None,
                "download_url": None,
                "expires_at": None,
                "row_count": 0,
            }
            log.info(
                "task.generate_export.completed",
                tenant_id=tenant_id,
                export_type=export_type,
            )
            return result

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(bind=True, name="exports.cleanup_expired_exports")
def cleanup_expired_exports(self) -> dict:
    """Remove expired export files from object storage.

    Runs on a schedule (typically daily). Reads the export_log table for entries
    whose download URL has expired and deletes the corresponding objects from
    storage, then marks them as cleaned in the log.
    """
    log.info("task.cleanup_exports.started")
    # TODO: scan export_log for expired entries, delete from storage
    result = {
        "status": "completed",
        "files_removed": 0,
        "bytes_freed": 0,
    }
    log.info("task.cleanup_exports.completed", files_removed=0)
    return result
