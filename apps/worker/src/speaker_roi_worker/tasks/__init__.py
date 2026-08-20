"""Task registry — import all task modules so Celery discovers them."""

from speaker_roi_worker.tasks import analytics, exports, ingestion

__all__ = ["analytics", "exports", "ingestion"]
