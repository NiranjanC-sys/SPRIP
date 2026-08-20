"""Background worker: Celery application, queues and jobs.

Long analytical work does not belong in a request. A causal analysis run reads a tenant's whole
history, fits several models and writes an evidence bundle; it takes minutes, and a client that
holds a connection open for minutes is a client that times out behind a proxy it does not control
and then retries, doubling the load that was already too slow.
"""

from __future__ import annotations

from celery import Celery

from speaker_roi_core.config import get_settings
from speaker_roi_core.logging import get_logger

log = get_logger(__name__)


def create_celery_app() -> Celery:
    """Build the Celery application with Redis broker and result backend."""
    settings = get_settings()
    app = Celery("speaker_roi_worker")
    app.conf.update(
        broker_url=settings.redis.broker_url,
        result_backend=settings.redis.result_url,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_default_queue="default",
        task_routes={
            "speaker_roi_worker.tasks.analytics.*": {"queue": "analytics"},
            "speaker_roi_worker.tasks.ingestion.*": {"queue": "ingestion"},
            "speaker_roi_worker.tasks.exports.*": {"queue": "exports"},
        },
    )
    app.autodiscover_tasks(
        [
            "speaker_roi_worker.tasks.analytics",
            "speaker_roi_worker.tasks.ingestion",
            "speaker_roi_worker.tasks.exports",
        ]
    )
    log.info("worker.celery_app_created")
    return app


celery_app = create_celery_app()

__all__ = ["celery_app", "create_celery_app"]
