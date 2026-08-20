"""Prometheus metrics.

One rule governs every definition in this file: **a label value must come from a bounded
set.** Prometheus keeps a separate time series per label combination, so a single
``tenant_id`` label on a request counter turns one series into one per customer, and a
``path`` label carrying concrete identifiers turns it into one per URL ever requested. That
is how a metrics endpoint takes down the scrape target it was added to observe.

So: route *templates* not paths, ``tenant_bucket`` not ``tenant_id``, and error *codes* not
messages. Where per-tenant numbers are genuinely needed - quota consumption, analysis
concurrency - the value lives in Redis or Postgres and is read by an endpoint, not carried
as a metric label.

The second rule is narrower and cost the industry a lot of pages: **a histogram's buckets
have to match the thing being measured.** The default ``prometheus_client`` buckets top out
at 10 seconds, which is right for HTTP and useless for an analysis run that takes seven
minutes - every run lands in ``+Inf`` and the p95 reads as "greater than ten seconds", which
is true and worthless. Analysis stages therefore get their own bucket set spanning seconds to
hours.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client.core import CollectorRegistry as _Registry

CONTENT_TYPE: Final = "text/plain; version=0.0.4; charset=utf-8"

#: Latency buckets for HTTP. Dense where the SLO lives (50-500 ms), sparse in the tail. The
#: 30-second bucket exists because that is where a request that is about to be killed by the
#: gateway sits, and knowing how many of those there are is the difference between "slow" and
#: "timing out".
HTTP_BUCKETS: Final = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

#: Analysis stage buckets, spanning ten seconds to two hours. A full sensitivity suite is
#: nine to eleven pipeline runs, so the upper buckets are not hypothetical.
ANALYSIS_BUCKETS: Final = (
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1_200.0,
    1_800.0,
    3_600.0,
    7_200.0,
)

#: Ingestion buckets: a spreadsheet parse is seconds, a 200 MB workbook is minutes.
INGESTION_BUCKETS: Final = (0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 180.0, 600.0)

REGISTRY: Final[CollectorRegistry] = CollectorRegistry(auto_describe=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

http_requests = Counter(
    "speaker_roi_http_requests_total",
    "HTTP requests by route template, method and status class.",
    # ``status`` is the numeric code and ``route`` is the template. Both are bounded: the
    # routes are enumerated by the router at import time, and there are a few dozen codes.
    ["route", "method", "status"],
    registry=REGISTRY,
)

http_latency = Histogram(
    "speaker_roi_http_request_duration_seconds",
    "Wall-clock time to produce a response, measured inside the middleware.",
    ["route", "method"],
    buckets=HTTP_BUCKETS,
    registry=REGISTRY,
)

http_in_flight = Gauge(
    "speaker_roi_http_requests_in_flight",
    "Requests currently being served. Saturation, as distinct from latency.",
    registry=REGISTRY,
)

#: Refusals, split by error code. The reason this is separate from the status counter: a 422
#: from a validation failure and a 422 from ``NOT_ESTIMABLE`` are the same HTTP status and
#: completely different events - the first is a client bug and the second is the product
#: working correctly, so an alert on "422 rate" fires on the wrong one.
app_errors = Counter(
    "speaker_roi_app_errors_total",
    "Application errors by taxonomy code.",
    ["code", "status"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

auth_attempts = Counter(
    "speaker_roi_auth_attempts_total",
    "Authentication attempts by outcome. No user or tenant label, deliberately.",
    ["outcome", "method"],
    registry=REGISTRY,
)

sessions_active = Gauge(
    "speaker_roi_sessions_active",
    "Server-side sessions not yet expired or revoked.",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Database and storage
# ---------------------------------------------------------------------------

db_pool = Gauge(
    "speaker_roi_db_pool_connections",
    "Connection pool occupancy by state.",
    ["state"],  # checked_out | available | overflow
    registry=REGISTRY,
)

db_errors = Counter(
    "speaker_roi_db_errors_total",
    "Database errors by SQLSTATE. Bounded: PostgreSQL defines a finite set.",
    ["sqlstate"],
    registry=REGISTRY,
)

#: The one that should always read zero. A non-zero value means a query reached the database
#: without a tenant bound and the RLS predicate raised - which is a wiring defect, and the
#: only metric here that justifies paging someone on a single increment.
rls_violations = Counter(
    "speaker_roi_rls_context_missing_total",
    "Queries that reached PostgreSQL with no tenant bound. Should always be zero.",
    registry=REGISTRY,
)

storage_operations = Counter(
    "speaker_roi_storage_operations_total",
    "Object storage operations by kind and outcome.",
    ["operation", "outcome"],
    registry=REGISTRY,
)

uploads_rejected = Counter(
    "speaker_roi_uploads_rejected_total",
    "Uploads refused before storage, by reason.",
    ["reason"],  # macro | executable | unsupported_type | too_large | empty | corrupt
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

ingestion_batches = Counter(
    "speaker_roi_ingestion_batches_total",
    "Ingestion batches by dataset and terminal state.",
    ["dataset", "state"],
    registry=REGISTRY,
)

ingestion_rows = Counter(
    "speaker_roi_ingestion_rows_total",
    "Rows processed by dataset and disposition.",
    ["dataset", "disposition"],  # accepted | rejected | warned
    registry=REGISTRY,
)

ingestion_duration = Histogram(
    "speaker_roi_ingestion_duration_seconds",
    "Time to validate and load one batch.",
    ["dataset"],
    buckets=INGESTION_BUCKETS,
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

analysis_runs = Counter(
    "speaker_roi_analysis_runs_total",
    "Analysis runs by terminal state.",
    ["state"],  # succeeded | failed | not_estimable | cancelled
    registry=REGISTRY,
)

analysis_stage_duration = Histogram(
    "speaker_roi_analysis_stage_duration_seconds",
    "Time per analysis stage. Buckets span seconds to hours; see module docstring.",
    ["stage"],  # panel | match | balance | estimate | sensitivity | evidence | roi
    buckets=ANALYSIS_BUCKETS,
    registry=REGISTRY,
)

analysis_in_flight = Gauge(
    "speaker_roi_analysis_runs_in_flight",
    "Analysis runs currently executing across all workers.",
    registry=REGISTRY,
)

#: The evidence grade distribution is a *product* metric, not an operational one, and it is
#: the most important number in this file. A sudden shift toward ``NOT_ESTIMABLE`` means the
#: data feeding the estimator changed - a vendor stopped submitting, a brand's event volume
#: collapsed - and nothing else in the system notices, because every individual run is
#: behaving exactly as designed.
evidence_grades = Counter(
    "speaker_roi_evidence_grades_total",
    "Analysis results by evidence grade.",
    ["grade"],  # STRONG | MODERATE | DIRECTIONAL | NOT_ESTIMABLE
    registry=REGISTRY,
)

gate_failures = Counter(
    "speaker_roi_evidence_gate_failures_total",
    "Individual credibility gates that failed, by gate name.",
    ["gate"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Forecasting and models
# ---------------------------------------------------------------------------

forecasts_served = Counter(
    "speaker_roi_forecasts_served_total",
    "Forecasts returned, by model and regime.",
    ["model", "mode"],  # mode: FITTED | POOLED | SHRUNK
    registry=REGISTRY,
)

forecast_fallbacks = Counter(
    "speaker_roi_forecast_fallbacks_total",
    "Forecasts that fell back rather than using the fitted model, by reason.",
    ["model", "reason"],  # out_of_support | insufficient_training | feature_drift
    registry=REGISTRY,
)

model_training_duration = Histogram(
    "speaker_roi_model_training_duration_seconds",
    "Time to fit a model, by model name.",
    ["model"],
    buckets=ANALYSIS_BUCKETS,
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Governed AI
# ---------------------------------------------------------------------------

ai_requests = Counter(
    "speaker_roi_ai_requests_total",
    "Narration requests by intent and outcome.",
    ["intent", "outcome"],  # outcome: served | refused | quota | fallback | provider_error
    registry=REGISTRY,
)

ai_tokens = Counter(
    "speaker_roi_ai_tokens_total",
    "Tokens consumed, split by direction. Cost control, not a performance metric.",
    ["direction"],  # input | output
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Background work
# ---------------------------------------------------------------------------

jobs = Counter(
    "speaker_roi_jobs_total",
    "Celery tasks by name and terminal state.",
    ["task", "state"],  # succeeded | failed | retried | dead_lettered
    registry=REGISTRY,
)

job_duration = Histogram(
    "speaker_roi_job_duration_seconds",
    "Task execution time.",
    ["task"],
    buckets=ANALYSIS_BUCKETS,
    registry=REGISTRY,
)

job_queue_depth = Gauge(
    "speaker_roi_job_queue_depth",
    "Messages waiting, by queue. Sampled, not exact.",
    ["queue"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def observe(histogram: Histogram, **labels: str) -> Iterator[None]:
    """Time a block into a histogram, recording on the failure path too.

    ``Histogram.time()`` also records on exception, but only as a decorator or bare context
    manager - this wrapper exists so the label values can be supplied at the call site, which
    is where the stage name is known.
    """
    with histogram.labels(**labels).time():
        yield


def render() -> bytes:
    """Serialise the registry for ``/metrics``.

    Under Gunicorn or a forking worker each process holds its own counters, and scraping one
    of them reports one worker's view as though it were the service's. ``PROMETHEUS_MULTIPROC_DIR``
    switches to the file-backed collector that aggregates across processes; without the
    variable set, the single-process registry is correct and this is a no-op.
    """
    import os

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry: _Registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest(REGISTRY)


def record_app_error(code: str, status: int) -> None:
    """Count a refusal by taxonomy code. Called from the exception handler, once."""
    app_errors.labels(code=code, status=str(status)).inc()


def record_pool_state(engine) -> None:
    """Sample the connection pool. Called by the readiness probe rather than continuously.

    Pool exhaustion is the failure that presents as "the whole API is slow" with every
    individual query fast, so these three numbers answer a question nothing else does.
    """
    pool = engine.pool
    for state, getter in (
        ("checked_out", "checkedout"),
        ("available", "checkedin"),
        ("overflow", "overflow"),
    ):
        value = getattr(pool, getter, None)
        if callable(value):
            db_pool.labels(state=state).set(float(value()))


__all__ = [
    "ANALYSIS_BUCKETS",
    "CONTENT_TYPE",
    "HTTP_BUCKETS",
    "INGESTION_BUCKETS",
    "REGISTRY",
    "ai_requests",
    "ai_tokens",
    "analysis_in_flight",
    "analysis_runs",
    "analysis_stage_duration",
    "app_errors",
    "auth_attempts",
    "db_errors",
    "db_pool",
    "evidence_grades",
    "forecast_fallbacks",
    "forecasts_served",
    "gate_failures",
    "http_in_flight",
    "http_latency",
    "http_requests",
    "ingestion_batches",
    "ingestion_duration",
    "ingestion_rows",
    "job_duration",
    "job_queue_depth",
    "jobs",
    "model_training_duration",
    "observe",
    "record_app_error",
    "record_pool_state",
    "render",
    "rls_violations",
    "sessions_active",
    "storage_operations",
    "uploads_rejected",
]
