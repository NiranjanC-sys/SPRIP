"""One-shot script to backfill planned_attendance on existing events."""

import asyncio
import random

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

random.seed(42)


async def fix_attendance():
    engine = create_async_engine(
        "postgresql+asyncpg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi",
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        # Get tenant
        row = await conn.execute(text("SELECT id FROM core.tenants WHERE code = 'demo-pharma'"))
        tenant_id = row.scalar_one()
        admin_row = await conn.execute(text("SELECT id FROM auth.users WHERE email = 'admin@demo.com'"))
        admin_id = admin_row.scalar_one()

        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        await conn.execute(text(f"SET app.identity_user_id = '{admin_id}'"))

        # Get all events without planned_attendance
        rows = await conn.execute(text(
            "SELECT id FROM core.events WHERE planned_attendance IS NULL"
        ))
        event_ids = [r[0] for r in rows]
        print(f"Found {len(event_ids)} events without planned_attendance")

        for eid in event_ids:
            pa = random.randint(50, 500)
            await conn.execute(text(
                "UPDATE core.events SET planned_attendance = :pa WHERE id = :eid"
            ), {"pa": pa, "eid": eid})

        print(f"Updated {len(event_ids)} events with planned_attendance")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(fix_attendance())
