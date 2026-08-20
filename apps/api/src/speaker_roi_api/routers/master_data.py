"""Brands, products, vendors and taxonomy values.

Thin by design. Everything that is easy to get wrong - the keyset window, the version check, the
audit pair, the constraint-violation translation - lives in :mod:`speaker_roi_api.services.crud`,
and each handler here is the part that is genuinely specific to its resource: which permission
guards it, which columns are filterable, and which fields are worth auditing.

Three decisions are visible in every handler and are worth stating once.

**Brand scope is applied to reads, not assumed.** A membership can be restricted to a subset of
brands, and row-level security cannot express that - it is per-user, not per-tenant. So the brand
and product list queries intersect with ``principal.brand_scope`` explicitly. This is the one
place in the application where an authorization filter is written in Python, and it is written
here because there is nowhere better for it; a reviewer should treat any *other* Python-level
tenant filter as a mistake.

**Vendors are administrative, not commercial.** They are guarded by ``VENDOR_*`` rather than
``BRAND_*``, and a vendor principal cannot read the vendor list at all. Letting one external
contributor enumerate the others is a competitive-intelligence leak with no upside.

**Taxonomy is tenant configuration**, so it is guarded by ``TENANT_READ`` / ``TENANT_WRITE``. It
looks like reference data and behaves like a schema: ingestion rejects spreadsheet values that do
not resolve against it, which means an accidental edit here breaks tomorrow's uploads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.common import Acknowledged, AuditStamp, Page
from speaker_roi_api.schemas.master_data import (
    BrandCreate,
    BrandOut,
    BrandPatch,
    DeactivateRequest,
    ProductCreate,
    ProductOut,
    ProductPatch,
    TaxonomyValueCreate,
    TaxonomyValueOut,
    TaxonomyValuePatch,
    VendorCreate,
    VendorGrantOut,
    VendorGrantRequest,
    VendorOut,
    VendorPatch,
    VendorStatusChange,
)
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import audit, crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.enums import AuditAction, DatasetAccess, TaxonomyKind, VendorStatus
from speaker_roi_core.errors import ForbiddenError, NotFoundError, ValidationError
from speaker_roi_core.models.core import (
    Brand,
    Product,
    TaxonomyValue,
    Vendor,
    VendorDatasetGrant,
)

router = APIRouter(tags=["Master data"])

#: The columns whose change a reviewer cares about, per resource.
#:
#: Explicit rather than "every column", because an audit diff that includes ``updated_at`` on
#: every row is an audit diff nobody reads. What belongs here is what someone would dispute.
_BRAND_AUDIT = ("code", "name", "therapeutic_area_code", "molecule", "is_active", "launch_date")
_PRODUCT_AUDIT = ("code", "name", "brand_id", "formulation", "strength", "pack_size", "is_active")
_VENDOR_AUDIT = ("code", "name", "status", "contact_email", "allowed_email_domains")
_TAXONOMY_AUDIT = ("kind", "code", "label", "parent_id", "sort_order", "is_active")


def _stamp(row: Any) -> AuditStamp:
    """Build the audit stamp every mutable resource carries.

    ``version`` is included on purpose: a client that never sees the token cannot send it back,
    and optimistic concurrency would then be a feature nothing uses.
    """
    return AuditStamp(
        created_at=row.created_at,
        updated_at=getattr(row, "updated_at", None),
        created_by=getattr(row, "created_by", None),
        updated_by=getattr(row, "updated_by", None),
        version=getattr(row, "row_version", None),
    )


def _actor_id() -> uuid.UUID | None:
    principal = current_principal()
    return principal.user_id if principal else None


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------


def _brand_out(row: Brand, product_count: int | None = None) -> BrandOut:
    return BrandOut(
        id=row.id,
        code=row.code,
        name=row.name,
        therapeutic_area_code=row.therapeutic_area_code,
        molecule=row.molecule,
        is_active=row.is_active,
        launch_date=row.launch_date,
        product_count=product_count,
        audit=_stamp(row),
    )


@router.get(
    "/brands",
    response_model=Page[BrandOut],
    summary="List brands",
    dependencies=[Depends(require(Permission.BRAND_READ))],
)
async def list_brands(
    db: ReadOnlySession,
    page: PageParams,
    q: Annotated[str | None, Query(max_length=100, description="Match on code or name")] = None,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> Page[BrandOut]:
    """Brands the caller may see, newest first.

    The product count comes from one grouped aggregate over the page's brand ids, not from a
    ``selectinload``. A brand with four hundred products would otherwise load four hundred ORM
    objects to render the number 400.
    """
    principal = current_principal()
    stmt = select(Brand)
    if not include_inactive:
        stmt = stmt.where(Brand.is_active.is_(True))
    if q:
        # Escaped, then matched with an explicit ESCAPE clause. Without it a caller searching
        # for "50%" matches every brand, which looks like a bug in the search box rather than
        # like the wildcard it is.
        pattern = f"%{q.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
        stmt = stmt.where(
            func.lower(Brand.name).like(pattern.lower(), escape="!")
            | Brand.code.like(pattern.lower(), escape="!")
        )
    if principal is not None and principal.brand_scope is not None:
        # The per-membership brand restriction. Not expressible in a row-level security policy
        # because it varies by user rather than by tenant, so it is applied here - and applied to
        # the *query*, not to the result, so a restricted user cannot page past their scope.
        stmt = stmt.where(Brand.id.in_(principal.brand_scope))

    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Brand.created_at, id_column=Brand.id
    )

    # One grouped count for the page, rather than a correlated subquery on the paginated
    # statement. The subquery reads better and does not survive ``paginate``, which uses
    # ``.scalars()`` and would silently discard the second column - returning brands with a null
    # product count and no error. Two queries that are obviously correct beat one that is
    # subtly wrong.
    counts: dict[uuid.UUID, int] = {}
    if rows:
        counted = await db.execute(
            select(Product.brand_id, func.count())
            .where(Product.brand_id.in_([r.id for r in rows]), Product.is_active.is_(True))
            .group_by(Product.brand_id)
        )
        counts = {brand: int(n) for brand, n in counted.all()}
    return Page(
        items=[_brand_out(r, product_count=counts.get(r.id, 0)) for r in rows],
        next_cursor=cursor,
    )


@router.post(
    "/brands",
    response_model=BrandOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a brand",
    dependencies=[Depends(require(Permission.BRAND_WRITE)), Depends(deny_vendor)],
)
async def create_brand(db: TenantSession, payload: BrandCreate) -> BrandOut:
    row = await crud.create(
        db,
        Brand,
        payload.model_dump(exclude_unset=True),
        resource="brand",
        audit_fields=_BRAND_AUDIT,
        label=payload.code,
        actor_id=_actor_id(),
    )
    return _brand_out(row, product_count=0)


@router.get(
    "/brands/{brand_id}",
    response_model=BrandOut,
    summary="Get a brand",
    dependencies=[Depends(require(Permission.BRAND_READ))],
)
async def get_brand(db: ReadOnlySession, brand_id: uuid.UUID) -> BrandOut:
    row = await crud.get_or_404(db, Brand, brand_id, resource="brand")
    _assert_brand_visible(brand_id)
    count = (
        await db.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.brand_id == brand_id, Product.is_active.is_(True))
        )
    ).scalar_one()
    return _brand_out(row, product_count=int(count))


@router.patch(
    "/brands/{brand_id}",
    response_model=BrandOut,
    summary="Update a brand",
    dependencies=[Depends(require(Permission.BRAND_WRITE)), Depends(deny_vendor)],
)
async def patch_brand(db: TenantSession, brand_id: uuid.UUID, payload: BrandPatch) -> BrandOut:
    row = await crud.get_or_404(db, Brand, brand_id, resource="brand")
    _assert_brand_visible(brand_id)
    await crud.update(
        db,
        row,
        crud.patch_changes(payload, "name", "therapeutic_area_code", "molecule", "launch_date"),
        resource="brand",
        audit_fields=_BRAND_AUDIT,
        expected_version=payload.version,
        label=row.code,
        actor_id=_actor_id(),
    )
    await db.refresh(row)
    return _brand_out(row)


@router.post(
    "/brands/{brand_id}/deactivate",
    response_model=Acknowledged,
    summary="Retire a brand",
    dependencies=[Depends(require(Permission.BRAND_WRITE)), Depends(deny_vendor)],
)
async def deactivate_brand(
    db: TenantSession, brand_id: uuid.UUID, payload: DeactivateRequest
) -> Acknowledged:
    """Retire a brand and every product under it.

    The cascade is done here rather than left to the caller because the alternative - a retired
    brand with active products - is a state the analytical layer cannot interpret: the products
    still aggregate into a brand that is no longer reported on, so a portfolio total silently
    stops matching the sum of its parts.
    """
    row = await crud.get_or_404(db, Brand, brand_id, resource="brand")
    _assert_brand_visible(brand_id)
    await crud.deactivate(
        db,
        row,
        resource="brand",
        audit_fields=_BRAND_AUDIT,
        status_field="is_active",
        inactive_value=False,
        reason=payload.reason,
        actor_id=_actor_id(),
    )
    products = (
        (await db.execute(select(Product).where(Product.brand_id == brand_id, Product.is_active)))
        .scalars()
        .all()
    )
    for product in products:
        await crud.deactivate(
            db,
            product,
            resource="product",
            audit_fields=_PRODUCT_AUDIT,
            status_field="is_active",
            inactive_value=False,
            reason=f"Brand {row.code} retired: {payload.reason}",
            actor_id=_actor_id(),
        )
    return Acknowledged()


def _assert_brand_visible(brand_id: uuid.UUID) -> None:
    """Enforce the per-membership brand restriction on a single-row read.

    Separate from the list filter because a single ``GET`` does not go through it, and an
    endpoint that returns a row the caller's list view cannot show them is exactly the kind of
    inconsistency an attacker enumerates. ``ForbiddenError`` rather than ``NotFoundError`` here:
    the brand demonstrably exists within the caller's own tenant, so concealing it would only
    mislead a legitimate user whose scope is narrower than they realise.
    """
    principal = current_principal()
    if principal is not None and not principal.may_see_brand(brand_id):
        raise ForbiddenError(
            "Your access is limited to a subset of brands, and this is not one of them.",
            remediation="Ask an administrator to widen your brand access.",
        )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def _product_out(row: Product, brand_name: str | None = None) -> ProductOut:
    return ProductOut(
        id=row.id,
        brand_id=row.brand_id,
        brand_name=brand_name,
        code=row.code,
        name=row.name,
        formulation=row.formulation,
        strength=row.strength,
        pack_size=row.pack_size,
        is_active=row.is_active,
        audit=_stamp(row),
    )


@router.get(
    "/products",
    response_model=Page[ProductOut],
    summary="List products",
    dependencies=[Depends(require(Permission.BRAND_READ))],
)
async def list_products(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> Page[ProductOut]:
    principal = current_principal()
    stmt = select(Product).options(selectinload(Product.brand))
    if brand_id is not None:
        _assert_brand_visible(brand_id)
        stmt = stmt.where(Product.brand_id == brand_id)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if principal is not None and principal.brand_scope is not None:
        stmt = stmt.where(Product.brand_id.in_(principal.brand_scope))

    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Product.created_at, id_column=Product.id
    )
    return Page(
        items=[_product_out(r, brand_name=r.brand.name if r.brand else None) for r in rows],
        next_cursor=cursor,
    )


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    dependencies=[Depends(require(Permission.BRAND_WRITE)), Depends(deny_vendor)],
)
async def create_product(db: TenantSession, payload: ProductCreate) -> ProductOut:
    """Create a product under an existing, active brand.

    The brand is fetched rather than relied upon as a foreign key, for two reasons: the FK cannot
    tell us whether the brand is *active*, and it cannot tell us whether it is inside the
    caller's brand scope. Both would otherwise be discovered as a constraint error or not at all.
    """
    brand = await crud.get_or_404(db, Brand, payload.brand_id, resource="brand")
    _assert_brand_visible(brand.id)
    if not brand.is_active:
        raise ValidationError(
            "That brand has been retired, so a new product cannot be added to it.",
            remediation="Reactivate the brand first, or choose another.",
        )
    row = await crud.create(
        db,
        Product,
        payload.model_dump(exclude_unset=True),
        resource="product",
        audit_fields=_PRODUCT_AUDIT,
        label=f"{brand.code}/{payload.code}",
        actor_id=_actor_id(),
    )
    return _product_out(row, brand_name=brand.name)


@router.get(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Get a product",
    dependencies=[Depends(require(Permission.BRAND_READ))],
)
async def get_product(db: ReadOnlySession, product_id: uuid.UUID) -> ProductOut:
    row = await crud.get_or_404(
        db, Product, product_id, resource="product", options=[selectinload(Product.brand)]
    )
    _assert_brand_visible(row.brand_id)
    return _product_out(row, brand_name=row.brand.name if row.brand else None)


@router.patch(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Update a product",
    dependencies=[Depends(require(Permission.BRAND_WRITE)), Depends(deny_vendor)],
)
async def patch_product(
    db: TenantSession, product_id: uuid.UUID, payload: ProductPatch
) -> ProductOut:
    row = await crud.get_or_404(db, Product, product_id, resource="product")
    _assert_brand_visible(row.brand_id)
    await crud.update(
        db,
        row,
        crud.patch_changes(payload, "name", "formulation", "strength", "pack_size"),
        resource="product",
        audit_fields=_PRODUCT_AUDIT,
        expected_version=payload.version,
        label=row.code,
        actor_id=_actor_id(),
    )
    await db.refresh(row)
    return _product_out(row)


@router.post(
    "/products/{product_id}/deactivate",
    response_model=Acknowledged,
    summary="Retire a product",
    dependencies=[Depends(require(Permission.BRAND_WRITE)), Depends(deny_vendor)],
)
async def deactivate_product(
    db: TenantSession, product_id: uuid.UUID, payload: DeactivateRequest
) -> Acknowledged:
    row = await crud.get_or_404(db, Product, product_id, resource="product")
    _assert_brand_visible(row.brand_id)
    await crud.deactivate(
        db,
        row,
        resource="product",
        audit_fields=_PRODUCT_AUDIT,
        status_field="is_active",
        inactive_value=False,
        reason=payload.reason,
        actor_id=_actor_id(),
    )
    return Acknowledged()


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def _vendor_out(row: Vendor, grants: list[VendorDatasetGrant] | None = None) -> VendorOut:
    return VendorOut(
        id=row.id,
        code=row.code,
        name=row.name,
        status=str(row.status),
        contact_email=row.contact_email,
        allowed_email_domains=row.allowed_email_domains,
        notes=row.notes,
        grants=[
            VendorGrantOut(
                id=g.id,
                dataset_type=str(g.dataset_type),
                access=str(g.access),
                granted_at=g.granted_at.isoformat(),
                revoked_at=g.revoked_at.isoformat() if g.revoked_at else None,
            )
            for g in (grants if grants is not None else [])
        ],
        audit=_stamp(row),
    )


@router.get(
    "/vendors",
    response_model=Page[VendorOut],
    summary="List vendors",
    dependencies=[Depends(require(Permission.VENDOR_READ)), Depends(deny_vendor)],
)
async def list_vendors(
    db: ReadOnlySession,
    page: PageParams,
    vendor_status: Annotated[VendorStatus | None, Query(alias="status")] = None,
) -> Page[VendorOut]:
    """The vendor register.

    ``deny_vendor`` as well as ``VENDOR_READ``, because an external contributor holding a
    read permission for its own record must not be able to enumerate the others. That is a
    competitive-intelligence leak with no legitimate use, and it is the exact case the
    belt-and-braces guard exists for.
    """
    stmt = select(Vendor).options(selectinload(Vendor.grants))
    if vendor_status is not None:
        stmt = stmt.where(Vendor.status == vendor_status)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Vendor.created_at, id_column=Vendor.id
    )
    return Page(items=[_vendor_out(r, list(r.grants)) for r in rows], next_cursor=cursor)


@router.post(
    "/vendors",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a vendor",
    dependencies=[Depends(require(Permission.VENDOR_WRITE)), Depends(deny_vendor)],
)
async def create_vendor(db: TenantSession, payload: VendorCreate) -> VendorOut:
    """Register a vendor. It starts with **no** dataset grants.

    Deliberately no default grant. A vendor that can submit nothing is a vendor that leaks
    nothing, and the administrator granting each dataset explicitly is the record of who decided
    that this agency may submit attendance.
    """
    row = await crud.create(
        db,
        Vendor,
        payload.model_dump(exclude_unset=True),
        resource="vendor",
        audit_fields=_VENDOR_AUDIT,
        label=payload.code,
        actor_id=_actor_id(),
    )
    return _vendor_out(row, [])


@router.get(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    summary="Get a vendor",
    dependencies=[Depends(require(Permission.VENDOR_READ)), Depends(deny_vendor)],
)
async def get_vendor(db: ReadOnlySession, vendor_id: uuid.UUID) -> VendorOut:
    row = await crud.get_or_404(
        db, Vendor, vendor_id, resource="vendor", options=[selectinload(Vendor.grants)]
    )
    return _vendor_out(row, list(row.grants))


@router.patch(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    summary="Update a vendor",
    dependencies=[Depends(require(Permission.VENDOR_WRITE)), Depends(deny_vendor)],
)
async def patch_vendor(db: TenantSession, vendor_id: uuid.UUID, payload: VendorPatch) -> VendorOut:
    row = await crud.get_or_404(db, Vendor, vendor_id, resource="vendor")
    await crud.update(
        db,
        row,
        crud.patch_changes(payload, "name", "contact_email", "allowed_email_domains", "notes"),
        resource="vendor",
        audit_fields=_VENDOR_AUDIT,
        expected_version=payload.version,
        label=row.code,
        actor_id=_actor_id(),
    )
    await db.refresh(row)
    return _vendor_out(row, [])


@router.post(
    "/vendors/{vendor_id}/status",
    response_model=VendorOut,
    summary="Suspend, terminate or reinstate a vendor",
    dependencies=[Depends(require(Permission.VENDOR_WRITE)), Depends(deny_vendor)],
)
async def change_vendor_status(
    db: TenantSession, vendor_id: uuid.UUID, payload: VendorStatusChange
) -> VendorOut:
    """Move a vendor between ``ACTIVE``, ``SUSPENDED`` and ``TERMINATED``.

    Termination revokes every live grant in the same transaction. Leaving them in place would
    mean a terminated vendor's stored API credential still satisfies an authorization check, and
    "we terminated them but the integration kept uploading" is the incident this prevents.

    Reinstating from ``TERMINATED`` does *not* restore the revoked grants. Access has to be
    granted again, deliberately, because the record of who re-authorised a terminated supplier is
    the point of terminating one.
    """
    row = await crud.get_or_404(
        db, Vendor, vendor_id, resource="vendor", options=[selectinload(Vendor.grants)]
    )
    previous = str(row.status)
    await crud.update(
        db,
        row,
        {"status": payload.status},
        resource="vendor",
        audit_fields=_VENDOR_AUDIT,
        label=row.code,
        actor_id=_actor_id(),
        reason=payload.reason,
    )
    if payload.status is VendorStatus.TERMINATED:
        now = datetime.now(UTC)
        for grant in row.grants:
            if grant.revoked_at is None:
                grant.revoked_at = now
        await db.flush()
        await audit.record(
            db,
            AuditAction.VENDOR_GRANT_REVOKED,
            resource_type="vendor",
            resource_id=row.id,
            resource_label=row.code,
            reason=f"Vendor terminated: {payload.reason}",
            after_state={"revoked_grants": len(row.grants), "previous_status": previous},
        )
    await db.refresh(row, attribute_names=["grants"])
    return _vendor_out(row, list(row.grants))


@router.post(
    "/vendors/{vendor_id}/grants",
    response_model=VendorGrantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a vendor access to one dataset",
    dependencies=[Depends(require(Permission.VENDOR_WRITE)), Depends(deny_vendor)],
)
async def grant_dataset(
    db: TenantSession, vendor_id: uuid.UUID, payload: VendorGrantRequest
) -> VendorGrantOut:
    """Grant, or re-grant, one dataset to one vendor.

    ``READ_WRITE`` on a dataset that carries prescription outcomes is refused outright rather
    than merely discouraged. plan.md §5.5 forbids ever showing prescription outcomes to a vendor,
    and a read-back grant on ``RX_MONTHLY`` would do exactly that - so the refusal lives here,
    where the grant is created, rather than at each of the several read paths that would
    otherwise each have to remember.
    """
    vendor = await crud.get_or_404(db, Vendor, vendor_id, resource="vendor")
    if vendor.status is not VendorStatus.ACTIVE:
        raise ValidationError(
            f"This vendor is {str(vendor.status).lower()}, so access cannot be granted.",
            remediation="Reinstate the vendor first.",
        )
    if payload.access is DatasetAccess.READ_WRITE and payload.dataset_type.carries_outcomes:
        raise ForbiddenError(
            "Read-back access cannot be granted on a dataset that carries prescription "
            "outcomes. This vendor may submit it, but never read it.",
            remediation="Grant WRITE access instead.",
        )

    existing = (
        await db.execute(
            select(VendorDatasetGrant).where(
                VendorDatasetGrant.vendor_id == vendor_id,
                VendorDatasetGrant.dataset_type == payload.dataset_type,
            )
        )
    ).scalar_one_or_none()

    actor = _actor_id()
    if existing is not None:
        # Re-granting an existing row rather than inserting a second: the unique constraint is on
        # (tenant, vendor, dataset_type), so a revoked grant is reinstated in place. The audit
        # trail carries the reinstatement, which is where that history belongs.
        existing.access = payload.access
        existing.revoked_at = None
        if actor is not None:
            existing.granted_by = actor
        await db.flush()
        grant = existing
        action = AuditAction.VENDOR_GRANT_GRANTED
    else:
        if actor is None:
            raise ForbiddenError("A dataset grant must be attributable to a named administrator.")
        grant = VendorDatasetGrant(
            vendor_id=vendor_id,
            dataset_type=payload.dataset_type,
            access=payload.access,
            granted_by=actor,
        )
        db.add(grant)
        await db.flush([grant])
        action = AuditAction.VENDOR_GRANT_GRANTED

    await audit.record(
        db,
        action,
        resource_type="vendor_dataset_grant",
        resource_id=grant.id,
        resource_label=f"{vendor.code}/{payload.dataset_type}",
        after_state={"dataset_type": str(payload.dataset_type), "access": str(payload.access)},
        status_code=201,
    )
    return VendorGrantOut(
        id=grant.id,
        dataset_type=str(grant.dataset_type),
        access=str(grant.access),
        granted_at=grant.granted_at.isoformat(),
        revoked_at=None,
    )


@router.delete(
    "/vendors/{vendor_id}/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a dataset grant",
    dependencies=[Depends(require(Permission.VENDOR_WRITE)), Depends(deny_vendor)],
)
async def revoke_grant(db: TenantSession, vendor_id: uuid.UUID, grant_id: uuid.UUID) -> Response:
    """Revoke a grant by stamping ``revoked_at``, not by deleting the row.

    The row is the evidence that access was once held, which is the first thing anyone asks for
    when a submission from six months ago is questioned.
    """
    grant = (
        await db.execute(
            select(VendorDatasetGrant).where(
                VendorDatasetGrant.id == grant_id, VendorDatasetGrant.vendor_id == vendor_id
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise NotFoundError("vendor_dataset_grant", grant_id)
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(UTC)
        await db.flush()
        await audit.record(
            db,
            AuditAction.VENDOR_GRANT_REVOKED,
            resource_type="vendor_dataset_grant",
            resource_id=grant.id,
            after_state={"dataset_type": str(grant.dataset_type), "revoked": True},
            status_code=204,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


def _taxonomy_out(row: TaxonomyValue) -> TaxonomyValueOut:
    return TaxonomyValueOut(
        id=row.id,
        kind=str(row.kind),
        code=row.code,
        label=row.label,
        parent_id=row.parent_id,
        sort_order=row.sort_order,
        is_active=row.is_active,
        audit=_stamp(row),
    )


@router.get(
    "/taxonomy",
    response_model=Page[TaxonomyValueOut],
    summary="List controlled vocabulary values",
    dependencies=[Depends(require(Permission.TENANT_READ))],
)
async def list_taxonomy(
    db: ReadOnlySession,
    page: PageParams,
    kind: Annotated[TaxonomyKind | None, Query()] = None,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> Page[TaxonomyValueOut]:
    """The tenant's controlled lists.

    Sorted by ``sort_order`` and not by recency, because this is the only list in the
    application whose order is *curated*: it populates dropdowns, and an administrator who put
    "Other" at the bottom expects it to stay there.
    """
    stmt = select(TaxonomyValue)
    if kind is not None:
        stmt = stmt.where(TaxonomyValue.kind == kind)
    if not include_inactive:
        stmt = stmt.where(TaxonomyValue.is_active.is_(True))
    rows, cursor, total = await crud.paginate(
        db,
        stmt,
        page,
        sort_column=TaxonomyValue.sort_order,
        id_column=TaxonomyValue.id,
        descending=False,
        with_total=True,
    )
    return Page(items=[_taxonomy_out(r) for r in rows], next_cursor=cursor, total=total)


@router.post(
    "/taxonomy",
    response_model=TaxonomyValueOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a controlled vocabulary value",
    dependencies=[Depends(require(Permission.TENANT_WRITE)), Depends(deny_vendor)],
)
async def create_taxonomy_value(
    db: TenantSession, payload: TaxonomyValueCreate
) -> TaxonomyValueOut:
    """Add one value to one controlled list.

    A ``parent_id`` must point at a value of the *same* kind. A specialty parented to a region
    would render as a nonsensical tree and, worse, would let an upload validate a city where a
    sub-specialty was expected - the kind of error that is only noticed when the analysis is
    already wrong.
    """
    if payload.parent_id is not None:
        parent = await crud.get_or_404(
            db, TaxonomyValue, payload.parent_id, resource="taxonomy_value"
        )
        if parent.kind is not payload.kind:
            raise ValidationError(
                "A value's parent must belong to the same controlled list.",
                internal_detail=f"parent kind {parent.kind} != {payload.kind}",
            )
    row = await crud.create(
        db,
        TaxonomyValue,
        payload.model_dump(exclude_unset=True),
        resource="taxonomy_value",
        audit_fields=_TAXONOMY_AUDIT,
        label=f"{payload.kind}/{payload.code}",
        actor_id=_actor_id(),
    )
    return _taxonomy_out(row)


@router.patch(
    "/taxonomy/{value_id}",
    response_model=TaxonomyValueOut,
    summary="Update a controlled vocabulary value",
    dependencies=[Depends(require(Permission.TENANT_WRITE)), Depends(deny_vendor)],
)
async def patch_taxonomy_value(
    db: TenantSession, value_id: uuid.UUID, payload: TaxonomyValuePatch
) -> TaxonomyValueOut:
    row = await crud.get_or_404(db, TaxonomyValue, value_id, resource="taxonomy_value")
    if payload.parent_id is not None:
        if payload.parent_id == value_id:
            raise ValidationError("A value cannot be its own parent.")
        parent = await crud.get_or_404(
            db, TaxonomyValue, payload.parent_id, resource="taxonomy_value"
        )
        if parent.kind is not row.kind:
            raise ValidationError("A value's parent must belong to the same controlled list.")
        if parent.parent_id == value_id:
            # One level of cycle detection, which is what a two-level hierarchy can produce.
            raise ValidationError("That parent would create a cycle in the hierarchy.")
    await crud.update(
        db,
        row,
        crud.patch_changes(payload, "label", "parent_id", "sort_order"),
        resource="taxonomy_value",
        audit_fields=_TAXONOMY_AUDIT,
        expected_version=payload.version,
        label=f"{row.kind}/{row.code}",
        actor_id=_actor_id(),
    )
    await db.refresh(row)
    return _taxonomy_out(row)


@router.post(
    "/taxonomy/{value_id}/deactivate",
    response_model=Acknowledged,
    summary="Retire a controlled vocabulary value",
    dependencies=[Depends(require(Permission.TENANT_WRITE)), Depends(deny_vendor)],
)
async def deactivate_taxonomy_value(
    db: TenantSession, value_id: uuid.UUID, payload: DeactivateRequest
) -> Acknowledged:
    """Retire a value. Existing rows that reference it keep their reference.

    Retirement stops the value appearing in dropdowns and stops new uploads resolving against
    it; it does not rewrite history. A region that was real last year stays attached to last
    year's events, because deleting it would silently re-bucket a completed analysis.
    """
    row = await crud.get_or_404(db, TaxonomyValue, value_id, resource="taxonomy_value")
    await crud.deactivate(
        db,
        row,
        resource="taxonomy_value",
        audit_fields=_TAXONOMY_AUDIT,
        status_field="is_active",
        inactive_value=False,
        reason=payload.reason,
        actor_id=_actor_id(),
    )
    return Acknowledged()


__all__ = ["router"]
