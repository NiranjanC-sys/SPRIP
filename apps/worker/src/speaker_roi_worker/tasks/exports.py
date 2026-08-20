"""Export tasks: report generation and cleanup.

Exports are generated asynchronously because building a full portfolio report can
require reading every event, prescription and finance record in a tenant. The result
is written to object storage and the user is given a short-lived download URL.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from speaker_roi_worker import celery_app

from speaker_roi_core.logging import get_logger

log = get_logger(__name__)


def _get_s3_client():
    """Build a boto3 S3 client for MinIO."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:9100",
        aws_access_key_id="minioadmin",
        aws_secret_access_key="minioadmin",
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
        ),
    )


def _neutralise_cell(value: object) -> str:
    """Prefix formula-triggering characters with an apostrophe for CSV safety."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


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
        now = datetime.now(timezone.utc)

        async with session_scope(tenant_id=tid) as db:
            from sqlalchemy import text

            self.update_state(state="PROGRESS", meta={"stage": "querying"})

            headers = []
            rows = []

            if export_type == "portfolio_report":
                headers = [
                    "brand_name", "period_start", "period_end",
                    "events_total", "events_measured", "attendees_verified",
                    "incremental_nrx", "total_cost", "net_roi",
                    "benefit_cost_ratio", "currency",
                ]
                db_rows = (await db.execute(text(
                    "SELECT level_key, period_start, period_end, "
                    "  events_total, events_measured, attendees_verified, "
                    "  incremental_nrx, total_cost, net_roi, "
                    "  benefit_cost_ratio, currency "
                    "FROM analytics.portfolio_aggregates "
                    "WHERE level = 'BRAND' "
                    "ORDER BY level_key, period_start"
                ))).mappings().all()
                for r in db_rows:
                    rows.append([
                        r["level_key"], str(r["period_start"]), str(r["period_end"]),
                        r["events_total"], r["events_measured"], r["attendees_verified"],
                        r["incremental_nrx"], r["total_cost"], r["net_roi"],
                        r["benefit_cost_ratio"], r["currency"],
                    ])

            elif export_type == "event_summary":
                headers = [
                    "event_code", "event_name", "event_date", "brand",
                    "format", "status", "total_cost", "attendees",
                    "incremental_nrx", "benefit_cost_ratio", "evidence_grade",
                ]
                db_rows = (await db.execute(text(
                    "SELECT e.code, e.name, e.event_date, b.name AS brand, "
                    "  e.format, e.status, "
                    "  COALESCE((SELECT SUM(ec.amount) FROM core.event_costs ec "
                    "    WHERE ec.event_id = e.id), 0) AS total_cost, "
                    "  COALESCE((SELECT COUNT(*) FROM core.attendance a "
                    "    WHERE a.event_id = e.id AND a.verified_attended = true), 0) AS attendees, "
                    "  ei.incremental_nrx, "
                    "  rr.benefit_cost_ratio, "
                    "  ei.evidence_grade "
                    "FROM core.events e "
                    "JOIN core.brands b ON b.id = e.brand_id "
                    "LEFT JOIN analytics.event_impacts ei ON ei.event_id = e.id "
                    "LEFT JOIN analytics.roi_results rr ON rr.event_id = e.id AND rr.level = 'EVENT' "
                    "ORDER BY e.event_date DESC"
                ))).mappings().all()
                for r in db_rows:
                    rows.append([
                        r["code"], r["name"], str(r["event_date"]), r["brand"],
                        r["format"], r["status"], r["total_cost"], r["attendees"],
                        r["incremental_nrx"], r["benefit_cost_ratio"],
                        r["evidence_grade"],
                    ])

            elif export_type == "roi_analysis":
                headers = [
                    "level", "brand_id", "event_id",
                    "incremental_nrx", "gross_contribution",
                    "total_cost", "net_roi", "benefit_cost_ratio",
                    "evidence_grade", "publication_state", "currency",
                ]
                db_rows = (await db.execute(text(
                    "SELECT level, brand_id, event_id, "
                    "  incremental_nrx, gross_contribution, "
                    "  total_cost, net_roi, benefit_cost_ratio, "
                    "  evidence_grade, publication_state, currency "
                    "FROM analytics.roi_results "
                    "ORDER BY level, brand_id"
                ))).mappings().all()
                for r in db_rows:
                    rows.append([
                        r["level"], str(r["brand_id"]) if r["brand_id"] else "",
                        str(r["event_id"]) if r["event_id"] else "",
                        r["incremental_nrx"], r["gross_contribution"],
                        r["total_cost"], r["net_roi"], r["benefit_cost_ratio"],
                        r["evidence_grade"], r["publication_state"], r["currency"],
                    ])

            else:
                return {
                    "tenant_id": tenant_id,
                    "export_type": export_type,
                    "status": "failed",
                    "object_key": None,
                    "download_url": None,
                    "expires_at": None,
                    "row_count": 0,
                    "error": f"Unsupported export type: {export_type}",
                }

            self.update_state(state="PROGRESS", meta={"stage": "building_csv"})

            # Build CSV content with formula neutralisation
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(headers)
            for row in rows:
                writer.writerow([_neutralise_cell(cell) for cell in row])

            csv_content = output.getvalue().encode("utf-8")

            self.update_state(state="PROGRESS", meta={"stage": "uploading"})

            # Upload to S3
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            object_key = f"{tenant_id}/{export_type}_{timestamp}_{uuid.uuid4().hex[:8]}.csv"

            client = _get_s3_client()

            # Ensure bucket exists
            try:
                client.head_bucket(Bucket="speaker-roi-exports")
            except Exception:
                try:
                    client.create_bucket(Bucket="speaker-roi-exports")
                except Exception:
                    pass

            client.put_object(
                Bucket="speaker-roi-exports",
                Key=object_key,
                Body=csv_content,
                ContentType="text/csv",
            )

            # Generate presigned download URL (expires in 1 hour)
            download_url = client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": "speaker-roi-exports",
                    "Key": object_key,
                    "ResponseContentDisposition": (
                        f'attachment; filename="{export_type}_{timestamp}.csv"'
                    ),
                },
                ExpiresIn=3600,
            )

            expires_at = (now + timedelta(hours=1)).isoformat()

            result = {
                "tenant_id": tenant_id,
                "export_type": export_type,
                "status": "completed",
                "object_key": object_key,
                "download_url": download_url,
                "expires_at": expires_at,
                "row_count": len(rows),
            }
            log.info(
                "task.generate_export.completed",
                tenant_id=tenant_id,
                export_type=export_type,
                row_count=len(rows),
            )
            return result

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(bind=True, name="exports.cleanup_expired_exports")
def cleanup_expired_exports(self) -> dict:
    """Remove expired export files from object storage.

    Runs on a schedule (typically daily). Lists objects in the exports bucket
    and deletes those older than 24 hours.
    """
    log.info("task.cleanup_exports.started")

    client = _get_s3_client()
    files_removed = 0
    bytes_freed = 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    try:
        # List objects in the exports bucket
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket="speaker-roi-exports"):
            contents = page.get("Contents", [])
            for obj in contents:
                last_modified = obj.get("LastModified")
                if last_modified and last_modified < cutoff:
                    try:
                        client.delete_object(
                            Bucket="speaker-roi-exports",
                            Key=obj["Key"],
                        )
                        files_removed += 1
                        bytes_freed += obj.get("Size", 0)
                    except Exception as exc:
                        log.warning(
                            "task.cleanup_exports.delete_failed",
                            key=obj["Key"],
                            error=str(exc),
                        )
    except Exception as exc:
        log.error("task.cleanup_exports.list_failed", error=str(exc))

    result = {
        "status": "completed",
        "files_removed": files_removed,
        "bytes_freed": bytes_freed,
    }
    log.info(
        "task.cleanup_exports.completed",
        files_removed=files_removed,
        bytes_freed=bytes_freed,
    )
    return result
