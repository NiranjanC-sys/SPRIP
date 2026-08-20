"""Router registry.

One explicit list rather than filesystem discovery. Discovery reads as less code and costs more:
a router that fails to import silently disappears from a discovered set, and the symptom is a 404
in production for an endpoint that exists in the source tree. An explicit list turns the same
mistake into an ImportError at start-up, which the orchestrator reports before the replica takes
traffic.

Order matters in exactly one way: FastAPI matches routes in registration order, so a literal path
must be registered before a parameterised one that would also match it. Within a module that is
the module's own business; across modules there is currently no overlap, and adding one would be
a design mistake rather than something to fix by reordering here.

The health router is *not* in this list. It is mounted without the API prefix, because a probe URL
that moves when the API is versioned is a probe that breaks on the next deployment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from speaker_roi_api.routers import (
    admin,
    analyses,
    audit_router,
    auth,
    campaigns,
    dashboard,
    events,
    exports,
    finance,
    forecasts,
    hcps,
    ingestion,
    master_data,
    optimizer,
    roi,
    tenants,
    users,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import APIRouter


def all_routers() -> Sequence[APIRouter]:
    """Every router mounted under the API prefix, in registration order."""
    return (
        auth.router,
        auth.me_router,
        master_data.router,
        hcps.router,
        campaigns.router,
        dashboard.router,
        events.router,
        finance.router,
        analyses.router,
        roi.router,
        forecasts.router,
        exports.router,
        optimizer.router,
        ingestion.router,
        audit_router.router,
        tenants.router,
        users.router,
        admin.router,
    )


__all__ = ["all_routers"]
