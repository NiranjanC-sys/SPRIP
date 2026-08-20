"""Response and request primitives shared by every router.

Two conventions are set here and never varied, because a client that has to handle two list
shapes or two error shapes ends up handling neither correctly.

**Every list response is a :class:`Page`.** Even the ones that will only ever return four rows,
because "this list is short" is a claim about today's data and the endpoint that outgrows it
does so in production. The envelope also carries ``next_cursor``, which is what lets the
frontend build one infinite-scroll component rather than one per screen.

**Every measured quantity that has uncertainty carries its interval and its evidence grade.**
:class:`Estimate` is the shape, and it has no plain-number alternative. That is the single most
important design decision in this file: a point estimate with the interval left off is how a
±40% confidence band becomes a slide that says "3.2x ROI", and the way to prevent it is to make
the number unrepresentable without its interval.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

T = TypeVar("T")


class Schema(BaseModel):
    """Base for every request and response model.

    ``extra="forbid"`` on requests is a security property rather than a style choice: a
    silently ignored unknown field is how a client believes it disabled a filter that the
    server never read. It is applied here, to *both* directions, so no request model can
    forget it.

    ``populate_by_name`` lets a response declare a Python-idiomatic attribute and a
    camelCase alias, so the API is idiomatic for its consumers without the backend adopting
    their naming.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        from_attributes=True,
        str_strip_whitespace=True,
        # Serialised as a string, not a float. A monetary amount that round-trips through
        # IEEE-754 is a monetary amount that stops reconciling, and this API's whole subject
        # is money.
        ser_json_inf_nan="strings",
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialise_decimal(self, value: Any) -> Any:
        return str(value) if isinstance(value, Decimal) else value


class Page(Schema, Generic[T]):
    """A keyset-paginated list.

    ``total`` is deliberately optional and deliberately absent from the hot paths. An exact
    count on a filtered, RLS-policied table is a full scan, so an endpoint that returns it on
    every page has traded its own latency for a number the user glances at. It is populated
    only where the count is itself the answer.
    """

    items: list[T]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None


class Interval(Schema):
    """A two-sided uncertainty interval, with the level it was computed at.

    ``level`` is carried rather than assumed to be 0.95, because the forecast endpoints
    legitimately serve 80% intervals - a decision-support interval, not a publication one -
    and a client that assumes 95% would draw an 80% band and label it 95%.
    """

    lower: float
    upper: float
    level: float = 0.95
    #: ``ANALYTIC`` | ``BOOTSTRAP`` | ``CONFORMAL``. Present because the three are not
    #: interchangeable in interpretation: a conformal band covers a *future observation*
    #: while a bootstrap CI covers a *parameter*, and a reader shown both without labels
    #: will compare their widths as if they meant the same thing.
    method: str | None = None


class Estimate(Schema):
    """A causal or predictive quantity with everything needed to read it honestly.

    ``value`` is optional. When the evidence gates refuse, the estimate is returned with a
    null value, a populated ``grade`` of ``NOT_ESTIMABLE`` and a ``reason`` - rather than
    omitted from the payload, which would let the frontend render a blank where a refusal
    belongs, or zero, which is a wrong answer rather than no answer.
    """

    value: float | None = None
    interval: Interval | None = None
    #: ``STRONG`` | ``MODERATE`` | ``DIRECTIONAL`` | ``NOT_ESTIMABLE``. Derived from hard
    #: gates, never from a learned confidence score - a model's self-reported certainty is
    #: not evidence about the world.
    grade: str
    #: Populated when ``grade`` is ``NOT_ESTIMABLE``: which gate failed, in language a brand
    #: manager can act on.
    reason: str | None = None
    unit: str | None = None
    #: Standard error, for the analyst-facing views that need to combine estimates.
    standard_error: float | None = Field(default=None, alias="standardError")


class Money(Schema):
    """An amount with its currency and, where converted, the rate that converted it.

    ``fx_rate_date`` is not decoration. A portfolio total in INR built from USD costs is
    only reproducible if the rate date travels with it, and "the number changed and nobody
    changed anything" is otherwise the most common finance complaint in a multi-currency
    product.
    """

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    fx_rate_date: date | None = Field(default=None, alias="fxRateDate")
    original_amount: Decimal | None = Field(default=None, alias="originalAmount")
    original_currency: str | None = Field(default=None, alias="originalCurrency")


class AuditStamp(Schema):
    """Who last touched a record and when. Attached to every mutable resource."""

    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    created_by: uuid.UUID | None = Field(default=None, alias="createdBy")
    updated_by: uuid.UUID | None = Field(default=None, alias="updatedBy")
    #: Optimistic-concurrency token. A client that PATCHes without it, or with a stale one,
    #: gets a 412 rather than silently overwriting a colleague's edit - which is the whole
    #: point of returning it.
    version: int | None = None


class Accepted(Schema):
    """The 202 body for work that runs in the background.

    Everything expensive in this application - an analysis run, an optimizer solve, an
    export - returns this rather than blocking. That is not only about timeouts: a request
    that holds a connection for eight minutes holds a database session and a worker slot,
    and thirty concurrent ones exhaust the pool for every other tenant.
    """

    job_id: uuid.UUID = Field(alias="jobId")
    status: str
    #: Where to poll. Returned explicitly so the client does not construct URLs, which is
    #: how a client ends up depending on a route shape we wanted to change.
    status_url: str = Field(alias="statusUrl")
    #: Best-effort, from historical durations for this job kind at this data scale. Null when
    #: there is no history to base it on, rather than a guess presented as an estimate.
    estimated_seconds: int | None = Field(default=None, alias="estimatedSeconds")


class Acknowledged(Schema):
    """A minimal body for a successful mutation that has nothing to return."""

    ok: Literal[True] = True


SortDirection = Annotated[Literal["asc", "desc"], Field(description="Sort direction")]

__all__ = [
    "Accepted",
    "Acknowledged",
    "AuditStamp",
    "Estimate",
    "Interval",
    "Money",
    "Page",
    "Schema",
    "SortDirection",
]
