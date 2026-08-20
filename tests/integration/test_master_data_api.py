"""Master data over HTTP: authentication, isolation, concurrency, paging, refusals.

Brands are the subject only because they are the simplest resource that has all the interesting
machinery attached - a permission guard, a version token, a keyset cursor, a cascade and a
row-level-security policy. What is actually under test is that machinery, and it is shared by
twenty-two other resources, so a regression caught here is a regression caught everywhere.

Each test asserts one behaviour that has a specific way of going wrong in production:

- the first-login flow works at all (an administrator who cannot enrol is an unusable tenant);
- one tenant cannot read another's rows, and is told 404 rather than 403;
- a stale write is refused with 412 instead of silently overwriting;
- a cursor round-trips through base64 and back into a ``timestamptz`` comparison;
- a corrupted cursor is refused rather than quietly treated as page one;
- an unknown field in a request body is rejected rather than ignored.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import API, sign_in

if TYPE_CHECKING:
    from httpx import AsyncClient

    from tests.integration.conftest import Actor

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _make_brand(client: AsyncClient, code: str, name: str) -> dict:
    response = await client.post(
        f"{API}/brands", json={"code": code, "name": name, "therapeuticAreaCode": "cardiology"}
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def test_first_login_requires_and_permits_enrolment(client: AsyncClient, demo: Actor) -> None:
    """A freshly bootstrapped administrator can complete enrolment and then do work.

    This is the deadlock test. ``PHARMA_ADMIN`` requires a second factor on every request, and the
    endpoints that create one are themselves behind the principal dependency - so if that
    dependency does not make a narrow exception for an account that has no factor *yet*, the only
    thing a new tenant's administrator can do is sign in and be refused.
    """
    login = await client.post(
        f"{API}/auth/login", json={"email": demo.email, "password": demo.password}
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["mfaRequired"] is True
    assert body["mfaEnrolmentRequired"] is True
    assert body["activeTenantId"] == str(demo.tenant_id)

    # Before enrolling, a guarded endpoint must refuse. 401 with a machine-readable code, not a
    # 403: the client's correct response is to send the user to the second-factor screen, and it
    # can only know that from the code.
    refused = await client.get(f"{API}/brands")
    assert refused.status_code == 401, refused.text
    assert refused.json()["error"]["code"] == "MFA_REQUIRED"

    await sign_in(client, demo)

    allowed = await client.get(f"{API}/brands")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["items"] == []


async def test_second_enrolment_attempt_needs_a_satisfied_session(
    client: AsyncClient, demo: Actor
) -> None:
    """Once enrolled, the enrolment endpoint stops being reachable without the factor.

    The mirror image of the test above, and the reason that one is safe. If the exception applied
    whenever a caller *asked* to enrol, anyone holding a stolen password could replace the
    authenticator and walk straight past the second factor.
    """
    await sign_in(client, demo)
    me = await client.get(f"{API}/me")
    assert me.status_code == 200, me.text
    assert me.json()["user"]["mfaEnrolled"] is True

    # Start a second session that stops after the password step.
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    transport = client._transport
    assert isinstance(transport, ASGITransport)
    async with Client(transport=transport, base_url="http://testserver") as pending:
        login = await pending.post(
            f"{API}/auth/login", json={"email": demo.email, "password": demo.password}
        )
        assert login.status_code == 200, login.text
        assert login.json()["mfaEnrolmentRequired"] is False
        blocked = await pending.post(f"{API}/auth/mfa/enrol")
        assert blocked.status_code == 401, blocked.text
        assert blocked.json()["error"]["code"] == "MFA_REQUIRED"


# ---------------------------------------------------------------------------
# The resource itself
# ---------------------------------------------------------------------------


async def test_brand_lifecycle(client: AsyncClient, demo: Actor) -> None:
    """Create, read, patch and retire, with the audit stamp and version present throughout."""
    await sign_in(client, demo)

    created = await _make_brand(client, "cardiozen", "CardioZen")
    assert created["code"] == "cardiozen"
    assert created["isActive"] is True
    assert created["productCount"] == 0
    assert created["audit"]["version"] == 1
    brand_id = created["id"]

    fetched = await client.get(f"{API}/brands/{brand_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["name"] == "CardioZen"

    patched = await client.patch(
        f"{API}/brands/{brand_id}",
        json={"name": "CardioZen XR", "version": created["audit"]["version"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "CardioZen XR"
    assert patched.json()["audit"]["version"] == 2

    retired = await client.post(
        f"{API}/brands/{brand_id}/deactivate",
        json={"reason": "Withdrawn from the market in this affiliate."},
    )
    assert retired.status_code == 200, retired.text

    # Gone from the default list, present when inactive rows are asked for explicitly. A retired
    # brand that vanishes entirely would take its history with it.
    listing = await client.get(f"{API}/brands")
    assert [b["id"] for b in listing.json()["items"]] == []
    with_inactive = await client.get(f"{API}/brands", params={"includeInactive": "true"})
    assert [b["id"] for b in with_inactive.json()["items"]] == [brand_id]


async def test_stale_version_is_refused_with_412(client: AsyncClient, demo: Actor) -> None:
    """The second of two concurrent editors gets a 412, not a silent overwrite.

    412 rather than 409 on purpose: the request is well-formed and the conflict is with a
    precondition the client supplied, which is exactly what 412 means. A 409 would suggest the
    resource state is inconsistent and invite a retry of the same body, which would fail again.
    """
    await sign_in(client, demo)
    created = await _make_brand(client, "neurofix", "NeuroFix")
    brand_id = created["id"]

    first = await client.patch(
        f"{API}/brands/{brand_id}", json={"molecule": "atorvastatin", "version": 1}
    )
    assert first.status_code == 200, first.text

    second = await client.patch(
        f"{API}/brands/{brand_id}", json={"molecule": "rosuvastatin", "version": 1}
    )
    assert second.status_code == 412, second.text
    error = second.json()["error"]
    assert error["code"] == "PRECONDITION_FAILED"
    assert error["remediation"]

    # And the losing write did not land.
    current = await client.get(f"{API}/brands/{brand_id}")
    assert current.json()["molecule"] == "atorvastatin"


async def test_unknown_request_field_is_rejected(client: AsyncClient, demo: Actor) -> None:
    """``extra="forbid"`` is a security property, not a style choice.

    A silently ignored field is how a client comes to believe it disabled a filter, restricted a
    scope or set a flag that the server never read.
    """
    await sign_in(client, demo)
    response = await client.post(
        f"{API}/brands", json={"code": "ghost", "name": "Ghost", "isActive": False}
    )
    assert response.status_code == 422, response.text


async def test_duplicate_code_is_a_409_without_leaking_the_constraint(
    client: AsyncClient, demo: Actor
) -> None:
    """A unique violation becomes a 409 whose message names the resource, never the index."""
    await sign_in(client, demo)
    await _make_brand(client, "dupe", "Dupe One")
    clash = await client.post(f"{API}/brands", json={"code": "dupe", "name": "Dupe Two"})
    assert clash.status_code == 409, clash.text
    message = clash.json()["error"]["message"]
    assert "already exists" in message
    assert "uq_" not in message and "constraint" not in message.lower()


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


async def test_another_tenants_brand_is_not_found(
    client: AsyncClient, app: object, demo: Actor, rival: Actor
) -> None:
    """Row-level security hides the row, and the API reports 404 rather than 403.

    403 would confirm that a record with that id exists somewhere in the platform, which is a
    cross-tenant information leak achieved entirely through status codes - enumerable, and
    invisible in any log that only records successful reads.
    """
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    # The rival creates a brand in its own tenant.
    transport = client._transport
    assert isinstance(transport, ASGITransport)
    async with Client(transport=transport, base_url="http://testserver") as other:
        await sign_in(other, rival)
        secret = await _make_brand(other, "rivalbrand", "Rival Brand")

    await sign_in(client, demo)
    for path in (f"{API}/brands/{secret['id']}", f"{API}/brands/{secret['id']}"):
        response = await client.get(path)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "NOT_FOUND"

    patch = await client.patch(f"{API}/brands/{secret['id']}", json={"name": "Taken"})
    assert patch.status_code == 404, patch.text

    # And it is absent from the list, which is the same guarantee stated the other way round.
    listing = await client.get(f"{API}/brands", params={"includeInactive": "true"})
    assert secret["id"] not in [b["id"] for b in listing.json()["items"]]


async def test_unknown_brand_id_is_also_404(client: AsyncClient, demo: Actor) -> None:
    """The indistinguishability the test above depends on: a real foreign row and a fictional one
    must produce the same response, or the difference between them is the leak."""
    await sign_in(client, demo)
    response = await client.get(f"{API}/brands/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


async def test_cursor_pages_the_whole_set_exactly_once(client: AsyncClient, demo: Actor) -> None:
    """Every row appears on exactly one page.

    The property worth testing is not "a cursor is returned" but "the union of the pages is the
    set, with no duplicates". Offset paging passes the first and fails the second the moment rows
    share a sort value, and the id tiebreaker in ``paginate`` is what makes keyset paging not do
    that - several of these brands will share a ``created_at`` to the microsecond.
    """
    await sign_in(client, demo)
    codes = [f"brand{index:02d}" for index in range(7)]
    for code in codes:
        await _make_brand(client, code, code.upper())

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # a bound, so a cursor that never terminates fails rather than hangs
        params = {"limit": "3"} | ({"cursor": cursor} if cursor else {})
        page = await client.get(f"{API}/brands", params=params)
        assert page.status_code == 200, page.text
        body = page.json()
        assert len(body["items"]) <= 3
        seen.extend(item["code"] for item in body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            break
    else:  # pragma: no cover - only on a paging bug
        pytest.fail("pagination did not terminate")

    assert sorted(seen) == sorted(codes)
    assert len(seen) == len(set(seen))


async def test_corrupt_cursor_is_refused(client: AsyncClient, demo: Actor) -> None:
    """A bad cursor is a 400, never a silent reset to page one.

    Silently restarting is the dangerous behaviour: the client believes it is on page nine, so
    whatever it is assembling gets the first page's rows a second time and no error to explain the
    duplicates.
    """
    await sign_in(client, demo)
    await _make_brand(client, "cursorbrand", "Cursor Brand")
    response = await client.get(f"{API}/brands", params={"cursor": "not-a-real-cursor"})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


async def test_page_size_is_capped(client: AsyncClient, demo: Actor) -> None:
    """A caller asking for a hundred thousand rows is refused, not obliged."""
    await sign_in(client, demo)
    response = await client.get(f"{API}/brands", params={"limit": "100000"})
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Products, for the cascade and the cross-resource reference
# ---------------------------------------------------------------------------


async def test_retiring_a_brand_retires_its_products(client: AsyncClient, demo: Actor) -> None:
    """The cascade exists because the alternative is uninterpretable.

    An active product under a retired brand still aggregates into a brand nobody reports on, so a
    portfolio total silently stops matching the sum of its parts - a discrepancy that surfaces
    weeks later in a finance review with no way to explain it.
    """
    await sign_in(client, demo)
    brand = await _make_brand(client, "cascade", "Cascade")
    product = await client.post(
        f"{API}/products",
        json={"brandId": brand["id"], "code": "cascade-10", "name": "Cascade 10mg"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]

    listing = await client.get(f"{API}/brands")
    assert next(b for b in listing.json()["items"] if b["id"] == brand["id"])["productCount"] == 1

    retired = await client.post(
        f"{API}/brands/{brand['id']}/deactivate", json={"reason": "Portfolio consolidation."}
    )
    assert retired.status_code == 200, retired.text

    after = await client.get(f"{API}/products/{product_id}")
    assert after.status_code == 200, after.text
    assert after.json()["isActive"] is False


async def test_product_cannot_reference_another_tenants_brand(
    client: AsyncClient, demo: Actor, rival: Actor
) -> None:
    """A foreign key to an invisible row is a validation error, not a 500.

    The insert fails at the database because the referenced brand is outside the policy, and the
    important part is the translation: an unmapped ``IntegrityError`` would surface as a 500 with a
    correlation id, telling the user nothing and paging someone for a client mistake.
    """
    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    transport = client._transport
    assert isinstance(transport, ASGITransport)
    async with Client(transport=transport, base_url="http://testserver") as other:
        await sign_in(other, rival)
        foreign = await _make_brand(other, "foreignbrand", "Foreign Brand")

    await sign_in(client, demo)
    response = await client.post(
        f"{API}/products",
        json={"brandId": foreign["id"], "code": "sneaky", "name": "Sneaky"},
    )
    assert response.status_code in {400, 404, 422}, response.text
    assert "does not exist" in response.json()["error"]["message"].lower() or (
        response.status_code in {404, 422}
    )
