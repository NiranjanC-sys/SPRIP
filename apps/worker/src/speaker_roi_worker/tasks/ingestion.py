"""Ingestion tasks: CSV upload processing and validation.

Prescription data arrives as CSV uploads. Validation and processing happen in the worker
because a single file can contain hundreds of thousands of rows, and parsing, validating,
de-duplicating and inserting that volume synchronously would block the API process.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date

from speaker_roi_worker import celery_app

from speaker_roi_core.logging import get_logger

log = get_logger(__name__)

# Column name normalization map for common variations
_COLUMN_ALIASES = {
    "hcp_id": "hcp_id",
    "hcpid": "hcp_id",
    "hcp": "hcp_id",
    "brand_id": "brand_id",
    "brandid": "brand_id",
    "brand": "brand_id",
    "month": "month",
    "period": "month",
    "nrx": "nrx",
    "new_rx": "nrx",
    "trx": "trx",
    "total_rx": "trx",
    "lrx": "lrx",
    "legacy_rx": "lrx",
}

_REQUIRED_COLUMNS = {"hcp_id", "brand_id", "month"}


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


def _download_from_s3(object_key: str, bucket: str = "speaker-roi-uploads") -> bytes:
    """Download an object from S3/MinIO."""
    client = _get_s3_client()
    response = client.get_object(Bucket=bucket, Key=object_key)
    return response["Body"].read()


def _normalize_columns(headers: list[str]) -> dict[int, str]:
    """Map column indices to normalized column names."""
    mapping = {}
    for i, h in enumerate(headers):
        normalized = h.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in _COLUMN_ALIASES:
            mapping[i] = _COLUMN_ALIASES[normalized]
        else:
            mapping[i] = normalized
    return mapping


def _parse_date(value: str) -> date | None:
    """Try to parse a date string in common formats."""
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            parsed = date.fromisoformat(value) if fmt == "%Y-%m-%d" else None
            if parsed is None:
                from datetime import datetime as dt
                parsed = dt.strptime(value, fmt).date()
            # Normalize to first of month
            return date(parsed.year, parsed.month, 1)
        except (ValueError, TypeError):
            continue
    return None


def _is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _is_numeric(value: str) -> bool:
    """Check if a string is numeric."""
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


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
        rows_inserted = 0
        rows_skipped = 0
        errors = []

        # Download from S3
        try:
            csv_bytes = _download_from_s3(object_key)
        except Exception as exc:
            log.error(
                "task.process_rx.download_failed",
                tenant_id=tenant_id,
                object_key=object_key,
                error=str(exc),
            )
            return {
                "tenant_id": tenant_id,
                "upload_id": upload_id,
                "status": "failed",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "errors": [f"Failed to download file: {type(exc).__name__}"],
            }

        # Parse CSV
        csv_text = csv_bytes.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(csv_text))

        try:
            headers = next(reader)
        except StopIteration:
            return {
                "tenant_id": tenant_id,
                "upload_id": upload_id,
                "status": "failed",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "errors": ["CSV file is empty"],
            }

        col_map = _normalize_columns(headers)
        normalized_headers = set(col_map.values())

        # Check required columns
        missing = _REQUIRED_COLUMNS - normalized_headers
        if missing:
            return {
                "tenant_id": tenant_id,
                "upload_id": upload_id,
                "status": "failed",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "errors": [f"Missing required columns: {', '.join(sorted(missing))}"],
            }

        # Collect all rows
        all_rows = list(reader)
        total_rows = len(all_rows)
        self.update_state(state="PROGRESS", meta={"rows_processed": 0, "total_rows": total_rows})

        async with session_scope(tenant_id=tid) as db:
            from sqlalchemy import text

            # Build a set of existing keys for dedup
            existing = set()
            existing_rows = (await db.execute(text(
                "SELECT hcp_id, brand_id, month, product_id "
                "FROM core.hcp_rx_monthly "
                "LIMIT 500000"
            ))).all()
            for er in existing_rows:
                existing.add((str(er[0]), str(er[1]), str(er[2]), str(er[3])))

            batch = []
            for row_idx, row in enumerate(all_rows):
                row_num = row_idx + 2  # 1-indexed + header

                # Build row dict from column mapping
                row_data = {}
                for col_idx, col_name in col_map.items():
                    if col_idx < len(row):
                        row_data[col_name] = row[col_idx].strip()

                # Validate required fields
                hcp_id_str = row_data.get("hcp_id", "")
                brand_id_str = row_data.get("brand_id", "")
                month_str = row_data.get("month", "")

                if not hcp_id_str or not brand_id_str or not month_str:
                    errors.append(f"Row {row_num}: missing required field(s)")
                    rows_skipped += 1
                    continue

                if not _is_valid_uuid(hcp_id_str):
                    errors.append(f"Row {row_num}: invalid hcp_id UUID")
                    rows_skipped += 1
                    continue

                if not _is_valid_uuid(brand_id_str):
                    errors.append(f"Row {row_num}: invalid brand_id UUID")
                    rows_skipped += 1
                    continue

                month_val = _parse_date(month_str)
                if month_val is None:
                    errors.append(f"Row {row_num}: unparseable month '{month_str}'")
                    rows_skipped += 1
                    continue

                # Parse numeric fields
                nrx_str = row_data.get("nrx", "")
                trx_str = row_data.get("trx", "")

                nrx = None
                trx = None
                if nrx_str and _is_numeric(nrx_str):
                    nrx = float(nrx_str)
                    if nrx < 0:
                        errors.append(f"Row {row_num}: negative nrx")
                        rows_skipped += 1
                        continue
                if trx_str and _is_numeric(trx_str):
                    trx = float(trx_str)
                    if trx < 0:
                        errors.append(f"Row {row_num}: negative trx")
                        rows_skipped += 1
                        continue

                hcp_uuid = uuid.UUID(hcp_id_str)
                brand_uuid = uuid.UUID(brand_id_str)
                # Use brand_id as product_id placeholder when no product column
                product_id = brand_uuid

                # Dedup check
                dedup_key = (str(hcp_uuid), str(brand_uuid), str(month_val), str(product_id))
                if dedup_key in existing:
                    rows_skipped += 1
                    continue
                existing.add(dedup_key)

                batch.append({
                    "tid": tid,
                    "hcp_id": hcp_uuid,
                    "product_id": product_id,
                    "month": month_val,
                    "brand_id": brand_uuid,
                    "nrx": nrx,
                    "trx": trx,
                })

                # Bulk insert in batches of 500
                if len(batch) >= 500:
                    await db.execute(text(
                        "INSERT INTO core.hcp_rx_monthly "
                        "  (tenant_id, hcp_id, product_id, month, brand_id, "
                        "   nrx, trx, is_observed) "
                        "VALUES "
                        "  (:tid, :hcp_id, :product_id, :month, :brand_id, "
                        "   :nrx, :trx, true) "
                        "ON CONFLICT DO NOTHING"
                    ), batch)
                    rows_inserted += len(batch)
                    batch = []
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "rows_processed": row_idx + 1,
                            "total_rows": total_rows,
                        },
                    )

            # Insert remaining batch
            if batch:
                await db.execute(text(
                    "INSERT INTO core.hcp_rx_monthly "
                    "  (tenant_id, hcp_id, product_id, month, brand_id, "
                    "   nrx, trx, is_observed) "
                    "VALUES "
                    "  (:tid, :hcp_id, :product_id, :month, :brand_id, "
                    "   :nrx, :trx, true) "
                    "ON CONFLICT DO NOTHING"
                ), batch)
                rows_inserted += len(batch)

        # Cap errors list to avoid huge payloads
        if len(errors) > 100:
            errors = errors[:100] + [f"... and {len(errors) - 100} more errors"]

        result = {
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "status": "completed",
            "rows_inserted": rows_inserted,
            "rows_skipped": rows_skipped,
            "errors": errors,
        }
        log.info(
            "task.process_rx.completed",
            tenant_id=tenant_id,
            upload_id=upload_id,
            rows_inserted=rows_inserted,
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
    and duplicate detection -- so the user can fix the file before committing
    the actual import.
    """
    log.info(
        "task.validate_csv.started",
        tenant_id=tenant_id,
        upload_id=upload_id,
    )

    errors = []
    total_rows = 0
    error_rows = 0

    # Download from S3
    try:
        csv_bytes = _download_from_s3(object_key)
    except Exception as exc:
        log.error(
            "task.validate_csv.download_failed",
            tenant_id=tenant_id,
            object_key=object_key,
            error=str(exc),
        )
        return {
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "status": "failed",
            "valid": False,
            "total_rows": 0,
            "error_rows": 0,
            "errors": [f"Failed to download file: {type(exc).__name__}"],
        }

    # Parse CSV
    csv_text = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(csv_text))

    try:
        headers = next(reader)
    except StopIteration:
        return {
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "status": "completed",
            "valid": False,
            "total_rows": 0,
            "error_rows": 0,
            "errors": ["CSV file is empty"],
        }

    # Validate column names
    col_map = _normalize_columns(headers)
    normalized_headers = set(col_map.values())

    missing = _REQUIRED_COLUMNS - normalized_headers
    if missing:
        errors.append(f"Missing required columns: {', '.join(sorted(missing))}")

    # Validate each row
    seen_keys = set()
    duplicate_count = 0

    for row_idx, row in enumerate(reader):
        total_rows += 1
        row_num = row_idx + 2
        row_errors = []

        row_data = {}
        for col_idx, col_name in col_map.items():
            if col_idx < len(row):
                row_data[col_name] = row[col_idx].strip()

        # Check required fields
        hcp_id_str = row_data.get("hcp_id", "")
        brand_id_str = row_data.get("brand_id", "")
        month_str = row_data.get("month", "")

        if not hcp_id_str:
            row_errors.append("missing hcp_id")
        elif not _is_valid_uuid(hcp_id_str):
            row_errors.append("invalid hcp_id UUID format")

        if not brand_id_str:
            row_errors.append("missing brand_id")
        elif not _is_valid_uuid(brand_id_str):
            row_errors.append("invalid brand_id UUID format")

        if not month_str:
            row_errors.append("missing month")
        elif _parse_date(month_str) is None:
            row_errors.append(f"unparseable month '{month_str}'")

        # Check numeric fields
        for field in ("nrx", "trx", "lrx"):
            val = row_data.get(field, "")
            if val and not _is_numeric(val):
                row_errors.append(f"non-numeric {field} value '{val}'")
            elif val and float(val) < 0:
                row_errors.append(f"negative {field} value")

        # Duplicate check within file
        if hcp_id_str and brand_id_str and month_str:
            key = (hcp_id_str, brand_id_str, month_str)
            if key in seen_keys:
                duplicate_count += 1
                row_errors.append("duplicate row within file")
            seen_keys.add(key)

        if row_errors:
            error_rows += 1
            if len(errors) < 100:
                errors.append(f"Row {row_num}: {'; '.join(row_errors)}")

    if duplicate_count > 0 and len(errors) < 100:
        errors.append(f"Total duplicate rows within file: {duplicate_count}")

    valid = error_rows == 0 and not missing

    result = {
        "tenant_id": tenant_id,
        "upload_id": upload_id,
        "status": "completed",
        "valid": valid,
        "total_rows": total_rows,
        "error_rows": error_rows,
        "errors": errors,
    }
    log.info(
        "task.validate_csv.completed",
        tenant_id=tenant_id,
        upload_id=upload_id,
        valid=valid,
    )
    return result
