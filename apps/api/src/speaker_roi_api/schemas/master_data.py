"""Brands, products, vendors and the tenant's controlled vocabularies.

These four resources look like boilerplate CRUD and are not, for one reason: everything
downstream joins on them. A brand's `code` appears in every upload file, every export filename
and every saved view; a taxonomy value is what ingestion validates a spreadsheet cell against.
So the constraints here are not cosmetic - a `code` that is allowed to contain a comma breaks a
CSV round-trip, and one that is allowed to change breaks every stored reference to it.

Hence two rules that the patch models enforce by omission rather than by validation:

**`code` cannot be changed after creation.** It is absent from every `*Patch` model, so there is
no field to send. Renaming is what `name` is for. A mutable business key means the identifier in
last quarter's export no longer resolves, and the failure surfaces as "the report is wrong"
rather than as an error.

**Deactivation is a distinct operation, not a `PATCH` of `isActive`.** Retiring a brand that has
events attached has consequences the caller should have to ask for explicitly, and an audit entry
that says `RECORD_DEACTIVATED` is findable in a way that a diff of a boolean is not.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from speaker_roi_api.schemas.common import AuditStamp, Schema
from speaker_roi_core.enums import DatasetAccess, DatasetType, TaxonomyKind, VendorStatus

#: A business key: lowercase alphanumerics, dots, hyphens and underscores.
#:
#: Restrictive on purpose. These values end up in CSV columns, export filenames, URL path
#: segments and Excel cells, and each of those has a character that breaks it - a comma, a path
#: separator, a leading ``=`` that Excel evaluates as a formula. Allowing them and then escaping
#: at four different boundaries is four chances to miss one.
Code = Annotated[
    str,
    StringConstraints(
        min_length=2, max_length=60, strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    ),
]

Name = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=80, strip_whitespace=True)]

_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _clean_domains(value: list[str] | None) -> list[str] | None:
    """Normalise and reject anything that is not a bare domain.

    Specifically rejects a leading ``@`` and a full email address, both of which an
    administrator will type by reflex. Accepting ``@acme.com`` and then comparing it against the
    part of an address *after* the ``@`` would match nothing, and the failure appears much later
    as "invitations to this vendor silently never work".

    A module-level function rather than a method inherited or copied between the two models: a
    pydantic ``field_validator`` is a descriptor, so referencing the decorated attribute from a
    sibling class gets the wrapper rather than the function and silently validates nothing.
    """
    if value is None:
        return None
    cleaned: list[str] = []
    for raw in value:
        item = raw.strip().lower().lstrip("@")
        if not _DOMAIN.match(item):
            msg = f"{raw!r} is not a bare domain name (expected e.g. 'acme.com')"
            raise ValueError(msg)
        cleaned.append(item)
    return sorted(set(cleaned))


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------


class BrandCreate(Schema):
    code: Code
    name: Name
    therapeutic_area_code: Code | None = Field(default=None, validation_alias="therapeuticAreaCode")
    molecule: Name | None = None
    launch_date: date | None = Field(
        default=None,
        validation_alias="launchDate",
        description="Used by the analytical layer to refuse pre-launch comparison windows, "
        "where a zero prescription baseline is an artefact of the calendar rather than a "
        "measurable starting point.",
    )


class BrandPatch(Schema):
    """No ``code``. See the module docstring - the business key is immutable."""

    name: Name | None = None
    therapeutic_area_code: Code | None = Field(default=None, validation_alias="therapeuticAreaCode")
    molecule: Name | None = None
    launch_date: date | None = Field(default=None, validation_alias="launchDate")
    version: int | None = Field(
        default=None,
        description="Optimistic-concurrency token from the record you loaded. Omitting it "
        "accepts a last-write-wins update; sending a stale one is refused with 412.",
    )


class BrandOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    therapeutic_area_code: str | None = Field(
        default=None, serialization_alias="therapeuticAreaCode"
    )
    molecule: str | None = None
    is_active: bool = Field(serialization_alias="isActive")
    launch_date: date | None = Field(default=None, serialization_alias="launchDate")
    #: Number of products under this brand. Present because the list view needs it and the
    #: alternative is N+1 requests from the client to render one table.
    product_count: int | None = Field(default=None, serialization_alias="productCount")
    audit: AuditStamp | None = None


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


class ProductCreate(Schema):
    brand_id: uuid.UUID = Field(validation_alias="brandId")
    code: Code
    name: Name
    formulation: ShortText | None = None
    strength: ShortText | None = None
    pack_size: ShortText | None = Field(default=None, validation_alias="packSize")


class ProductPatch(Schema):
    """``brand_id`` is absent as well as ``code``.

    Re-parenting a product to a different brand silently rewrites the history of both brands'
    prescription aggregates, because the aggregation is a join through this column. If a product
    was filed under the wrong brand, the correct fix is to retire it and create the right one,
    which leaves the mistake visible instead of erasing it.
    """

    name: Name | None = None
    formulation: ShortText | None = None
    strength: ShortText | None = None
    pack_size: ShortText | None = Field(default=None, validation_alias="packSize")
    version: int | None = None


class ProductOut(Schema):
    id: uuid.UUID
    brand_id: uuid.UUID = Field(serialization_alias="brandId")
    brand_name: str | None = Field(default=None, serialization_alias="brandName")
    code: str
    name: str
    formulation: str | None = None
    strength: str | None = None
    pack_size: str | None = Field(default=None, serialization_alias="packSize")
    is_active: bool = Field(serialization_alias="isActive")
    audit: AuditStamp | None = None


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------


class VendorCreate(Schema):
    code: Code
    name: Name
    contact_email: str | None = Field(default=None, validation_alias="contactEmail", max_length=320)
    allowed_email_domains: list[str] | None = Field(
        default=None,
        validation_alias="allowedEmailDomains",
        max_length=20,
        description="Email domains a vendor user may be invited from. An empty list and a null "
        "are different: null means no domain restriction, an empty list means no invitation is "
        "possible at all.",
    )
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("allowed_email_domains")
    @classmethod
    def _check_domains(cls, value: list[str] | None) -> list[str] | None:
        return _clean_domains(value)


class VendorPatch(Schema):
    name: Name | None = None
    contact_email: str | None = Field(default=None, validation_alias="contactEmail", max_length=320)
    allowed_email_domains: list[str] | None = Field(
        default=None, validation_alias="allowedEmailDomains", max_length=20
    )
    notes: str | None = Field(default=None, max_length=4000)
    version: int | None = None

    @field_validator("allowed_email_domains")
    @classmethod
    def _check_domains(cls, value: list[str] | None) -> list[str] | None:
        return _clean_domains(value)


class VendorStatusChange(Schema):
    """Suspension and termination, with a mandatory reason.

    The reason is required rather than optional because this is the field a dispute is settled
    with six months later. ``status`` is changed through this endpoint rather than through
    ``PATCH`` so that the audit trail carries the reason alongside the transition.
    """

    status: VendorStatus
    reason: Annotated[str, StringConstraints(min_length=5, max_length=500, strip_whitespace=True)]


class VendorGrantOut(Schema):
    id: uuid.UUID
    dataset_type: str = Field(serialization_alias="datasetType")
    #: ``WRITE`` or ``READ_WRITE``. Directional on purpose: submitting attendance does not
    #: confer the right to read it back, because reading it exposes other vendors' submissions.
    access: str
    granted_at: str = Field(serialization_alias="grantedAt")
    revoked_at: str | None = Field(default=None, serialization_alias="revokedAt")


class VendorOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    status: str
    contact_email: str | None = Field(default=None, serialization_alias="contactEmail")
    allowed_email_domains: list[str] | None = Field(
        default=None, serialization_alias="allowedEmailDomains"
    )
    notes: str | None = None
    grants: list[VendorGrantOut] = Field(default_factory=list)
    audit: AuditStamp | None = None


class VendorGrantRequest(Schema):
    dataset_type: DatasetType = Field(validation_alias="datasetType")
    #: ``READ`` alone is not offered. A grant that lets a vendor read a dataset it cannot write
    #: has no use case here and would be the one shape that leaks another vendor's submissions
    #: without the grantee contributing anything, so the API does not expose it.
    access: Literal[DatasetAccess.WRITE, DatasetAccess.READ_WRITE] = DatasetAccess.WRITE


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class TaxonomyValueCreate(Schema):
    kind: TaxonomyKind
    code: Code
    label: Name
    parent_id: uuid.UUID | None = Field(default=None, validation_alias="parentId")
    sort_order: int = Field(default=0, validation_alias="sortOrder", ge=0, le=10_000)


class TaxonomyValuePatch(Schema):
    """``kind`` and ``code`` are both immutable.

    Changing ``kind`` would move a value between two controlled lists while every row that
    references it stays put, which produces a region used as a specialty. Changing ``code``
    breaks the upload files that spell it.
    """

    label: Name | None = None
    parent_id: uuid.UUID | None = Field(default=None, validation_alias="parentId")
    sort_order: int | None = Field(default=None, validation_alias="sortOrder", ge=0, le=10_000)
    version: int | None = None


class TaxonomyValueOut(Schema):
    id: uuid.UUID
    kind: str
    code: str
    label: str
    parent_id: uuid.UUID | None = Field(default=None, serialization_alias="parentId")
    sort_order: int = Field(serialization_alias="sortOrder")
    is_active: bool = Field(serialization_alias="isActive")
    audit: AuditStamp | None = None


class DeactivateRequest(Schema):
    """The body for every retirement endpoint.

    A reason, and nothing else. Uniform across resources so the audit query that answers "what
    was retired last quarter and why" is one query rather than one per table.
    """

    reason: Annotated[str, StringConstraints(min_length=5, max_length=500, strip_whitespace=True)]


__all__ = [
    "BrandCreate",
    "BrandOut",
    "BrandPatch",
    "Code",
    "DeactivateRequest",
    "ProductCreate",
    "ProductOut",
    "ProductPatch",
    "TaxonomyValueCreate",
    "TaxonomyValueOut",
    "TaxonomyValuePatch",
    "VendorCreate",
    "VendorGrantOut",
    "VendorGrantRequest",
    "VendorOut",
    "VendorPatch",
    "VendorStatusChange",
]
