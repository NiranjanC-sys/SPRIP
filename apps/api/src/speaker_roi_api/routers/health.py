"""Liveness, readiness and metrics. Unauthenticated, and separated on purpose.

Three endpoints rather than one, because an orchestrator asks three different questions and
answering them all with one probe causes outages.

``/livez`` answers *is this process wedged*. It touches nothing external. If it consulted the
database, a database blip would make Kubernetes restart every healthy replica simultaneously -
turning a recoverable dependency failure into a total outage, which is the single most common
way health checks cause the incident they were meant to detect.

``/readyz`` answers *should this replica receive traffic*, and therefore does check dependencies.
A failure here removes one replica from the load balancer and leaves it running, which is
recoverable.

``/healthz`` is the human-facing one: more detail, still no secrets, and it reports ``degraded``
distinctly from ``down`` - a database that is reachable but whose role bypasses row-level
security must not serve traffic, and that is a different call-out from an unreachable one.
"""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST

from speaker_roi_core import metrics
from speaker_roi_core.config import get_settings
from speaker_roi_core.db.session import get_engine, health

router = APIRouter(tags=["health"])


@router.get("/livez", summary="Process liveness", include_in_schema=False)
async def livez() -> dict[str, str]:
    """Always 200 while the event loop can schedule this coroutine.

    That is the entire claim, and it is a useful one: a process that cannot answer this has
    a deadlocked loop or has exhausted memory, and restarting it is the right response.
    """
    return {"status": "alive"}


@router.get("/readyz", summary="Readiness for traffic", include_in_schema=False)
async def readyz(response: Response) -> dict[str, Any]:
    """503 unless this replica can serve a real request.

    Includes the pool state, which is the field that explains the interesting failure: a
    replica that is "ready" but has zero free connections is about to time out every request,
    and the checked-out count is what makes that visible before it does.
    """
    state, detail = await health()
    if state != "ok":
        response.status_code = 503
    # Suppressed, not handled: a readiness probe that fails because instrumentation failed
    # would take a healthy replica out of the load balancer for a reason unrelated to whether
    # it can serve requests.
    with contextlib.suppress(Exception):
        metrics.record_pool_state(get_engine())
    return {"status": state, **_public(detail)}


@router.get("/healthz", summary="Detailed health")
async def healthz(response: Response) -> dict[str, Any]:
    """Operator-facing detail, including the build version and the RLS posture."""
    settings = get_settings()
    state, detail = await health()
    if state == "down":
        response.status_code = 503
    return {
        "status": state,
        "service": settings.app_name,
        "version": settings.version,
        "environment": settings.app_env,
        "database": _public(detail),
    }


def _public(detail: dict[str, Any]) -> dict[str, Any]:
    """Strip anything from the health payload that a caller should not read.

    The probe is unauthenticated, so its payload is public. ``check_connectivity`` returns
    the connected role name and the server version, which are exactly the two facts a
    reconnaissance scan wants: the role name to spray credentials at, the version to pick an
    exploit for. The *flags* derived from them are safe and are what an operator needs.
    """
    allowed = {
        "connected",
        "bypasses_rls",
        "is_superuser",
        "tenant_bound",
        "reason",
        "pool_size",
        "checked_out",
        "overflow",
    }
    return {k: v for k, v in detail.items() if k in allowed}


def metrics_router(path: str) -> APIRouter:
    """The Prometheus endpoint, mounted only when metrics are enabled.

    Built by a factory because the path is configurable, and returned as its own router so
    the app factory can decline to mount it at all. In a deployment that scrapes over a
    separate port, an unmounted endpoint is better than an open one: the metrics carry route
    templates and tenant-free counts, but they also carry enough traffic shape to be worth
    not publishing.
    """
    sub = APIRouter(tags=["health"])

    @sub.get(path, include_in_schema=False)
    async def prometheus() -> Response:
        return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)

    return sub


__all__ = ["metrics_router", "router"]
