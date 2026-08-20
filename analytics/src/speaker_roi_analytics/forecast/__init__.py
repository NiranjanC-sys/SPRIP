"""Forward-looking models: what a program that has not happened yet will do.

Two models, two very different statistical situations, and the difference is the whole
design::

    ImpactForecaster    -> ImpactForecast      (M3: incremental effect per attendee)
    AttendanceForecaster -> ReachForecast       (M4: who will actually turn up)
                         -> AttendanceForecast  (M4: cold start, design only)

:mod:`.impact` trains on the *output of the causal layer* - one row per measured,
graded program, each carrying an interval often wider than its own point estimate. There
are tens of such rows, not thousands, so it shrinks: an empirical-Bayes hierarchy whose
between-cell variance is estimated rather than assumed, and which collapses to the pooled
mean when segments turn out to be indistinguishable.

:mod:`.attendance` trains on one row per invitation, with a directly observed outcome. That
abundance is what makes a gradient-boosted learner right there and wrong in :mod:`.impact`.

**They compose through the attendee, and only through the attendee.** M3 forecasts effect
*per verified attendee*; M4 forecasts how many verified attendees there will be. The total
is their product, and :meth:`~.impact.ImpactForecast.scaled_to` combines the two intervals
in relative-variance space rather than multiplying endpoints, because how many people show
up and how strongly each responds are independent failures.

Both refuse rather than extrapolate. See
:data:`~speaker_roi_core.enums.ForecastMode`: ``OUT_OF_SUPPORT`` names the offending
feature and returns no number, because a number with a caveat loses its caveat on the way
into a slide.
"""

from __future__ import annotations

from .attendance import (
    EVENT_FEATURES,
    INVITATION_FEATURES,
    MIN_EVENTS_FOR_EVENT_MODEL,
    MIN_INVITATIONS,
    AttendanceForecast,
    AttendanceForecaster,
    AttendanceModelSpec,
    ReachForecast,
    ReachValidation,
)
from .impact import (
    CELL_KEYS,
    COVERAGE_TOLERANCE,
    MIN_CELL_EVENTS,
    MIN_TRAINING_EVENTS,
    TRAINING_COLUMNS,
    CellEstimate,
    ImpactForecast,
    ImpactForecaster,
    ImpactModelSpec,
    ValidationReport,
    prepare_training_frame,
)

__all__ = [
    "CELL_KEYS",
    "COVERAGE_TOLERANCE",
    "EVENT_FEATURES",
    "INVITATION_FEATURES",
    "MIN_CELL_EVENTS",
    "MIN_EVENTS_FOR_EVENT_MODEL",
    "MIN_INVITATIONS",
    "MIN_TRAINING_EVENTS",
    "TRAINING_COLUMNS",
    "AttendanceForecast",
    "AttendanceForecaster",
    "AttendanceModelSpec",
    "CellEstimate",
    "ImpactForecast",
    "ImpactForecaster",
    "ImpactModelSpec",
    "ReachForecast",
    "ReachValidation",
    "ValidationReport",
    "prepare_training_frame",
]
