"""Create brand-scoped demo users.

Each user gets a BRAND_MANAGER membership scoped to exactly one brand via
auth.membership_brand_scopes, so they can only see data for their brand.

Usage:
    python scripts/seed_brand_users.py
"""

import asyncio
import uuid
from datetime import datetime, timezone

TENANT_CODE = "demo-pharma"

BRAND_USERS = [
    {"email": "cardivex_user@demo.com", "display_name": "Cardivex User", "brand": "CARDIVEX"},
    {"email": "endostat_user@demo.com", "display_name": "Endostat User", "brand": "ENDOSTAT"},
    {"email": "neurovant_user@demo.com", "display_name": "Neurovant User", "brand": "NEUROVANT"},
    {"email": "oncolera_user@demo.com", "display_name": "Oncolera User", "brand": "ONCOLERA"},
]

PASSWORD = "brand@123"


async def main() -> None:
    from argon2 import PasswordHasher
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    ph = PasswordHasher()
    password_hash = ph.hash(PASSWORD)

    engine = create_async_engine(
        "postgresql+asyncpg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi",
        poolclass=NullPool,
    )

    async with engine.begin() as conn:
        # Resolve tenant
        row = await conn.execute(
            text("SELECT id FROM core.tenants WHERE code = :code"),
            {"code": TENANT_CODE},
        )
        tenant_id = row.scalar_one()
        print(f"Tenant: {tenant_id}")

        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        # Resolve admin for identity context
        row = await conn.execute(
            text("SELECT id FROM auth.users WHERE email = 'admin@demo.com'")
        )
        admin_id = row.scalar_one()
        await conn.execute(text(f"SET app.identity_user_id = '{admin_id}'"))

        # Load brand map
        rows = await conn.execute(text("SELECT id, name FROM core.brands"))
        brand_map = {r.name: r.id for r in rows}
        print(f"  Brands: {list(brand_map.keys())}")

        now = datetime.now(timezone.utc)

        for user_spec in BRAND_USERS:
            email = user_spec["email"]
            display_name = user_spec["display_name"]
            brand_name = user_spec["brand"]

            if brand_name not in brand_map:
                print(f"  WARNING: Brand '{brand_name}' not found, skipping {email}")
                continue

            brand_id = brand_map[brand_name]

            # Upsert user (ON CONFLICT on email)
            user_id = uuid.uuid4()
            result = await conn.execute(
                text("""
                    INSERT INTO auth.users
                        (id, email, display_name, status, auth_provider_kind,
                         password_hash, password_updated_at,
                         must_change_password, mfa_required, failed_login_count,
                         is_platform_admin, row_version, created_at, updated_at,
                         created_by, updated_by)
                    VALUES
                        (:id, :email, :dname, 'ACTIVE', 'LOCAL',
                         :pw_hash, :now,
                         false, false, 0,
                         false, 1, :now, :now,
                         :id, :id)
                    ON CONFLICT ((lower(email))) DO UPDATE
                        SET password_hash = :pw_hash,
                            password_updated_at = :now,
                            updated_at = :now
                    RETURNING id
                """),
                {
                    "id": user_id,
                    "email": email,
                    "dname": display_name,
                    "pw_hash": password_hash,
                    "now": now,
                },
            )
            user_id = result.scalar_one()
            print(f"  User: {email} -> {user_id}")

            # Upsert membership with all_brands=false (brand-scoped)
            membership_id = uuid.uuid4()
            result = await conn.execute(
                text("""
                    INSERT INTO auth.memberships
                        (id, tenant_id, user_id, role, status, all_brands,
                         row_version, created_at, updated_at, created_by, updated_by)
                    VALUES
                        (:id, :tid, :uid, 'BRAND_MANAGER', 'ACTIVE', false,
                         1, :now, :now, :admin, :admin)
                    ON CONFLICT (tenant_id, user_id, role) DO UPDATE
                        SET all_brands = false,
                            status = 'ACTIVE',
                            updated_at = :now
                    RETURNING id
                """),
                {
                    "id": membership_id,
                    "tid": tenant_id,
                    "uid": user_id,
                    "now": now,
                    "admin": admin_id,
                },
            )
            membership_id = result.scalar_one()
            print(f"    Membership: {membership_id} (BRAND_MANAGER, scoped)")

            # Upsert brand scope
            await conn.execute(
                text("""
                    INSERT INTO auth.membership_brand_scopes
                        (id, tenant_id, membership_id, brand_id,
                         created_at, updated_at, created_by, updated_by)
                    VALUES
                        (:id, :tid, :mid, :bid,
                         :now, :now, :admin, :admin)
                    ON CONFLICT (membership_id, brand_id) DO NOTHING
                """),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "mid": membership_id,
                    "bid": brand_id,
                    "now": now,
                    "admin": admin_id,
                },
            )
            print(f"    Brand scope: {brand_name} ({brand_id})")

    await engine.dispose()
    print("\n=== Brand users seed complete ===")


if __name__ == "__main__":
    asyncio.run(main())
