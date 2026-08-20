"""Generate sample rx_monthly CSV with real HCP/brand IDs from the database."""

import asyncio
import csv
import random
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

random.seed(42)

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"


async def main():
    engine = create_async_engine(
        "postgresql+asyncpg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi",
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        row = await conn.execute(text("SELECT id FROM core.tenants WHERE code = 'demo-pharma'"))
        tenant_id = row.scalar_one()
        admin_row = await conn.execute(text("SELECT id FROM auth.users WHERE email = 'admin@demo.com'"))
        admin_id = admin_row.scalar_one()

        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        await conn.execute(text(f"SET app.identity_user_id = '{admin_id}'"))

        rows = await conn.execute(text("SELECT id FROM core.hcps LIMIT 10"))
        hcp_ids = [str(r[0]) for r in rows]

        rows = await conn.execute(text("SELECT id, name FROM core.brands"))
        brands = [(str(r[0]), r[1]) for r in rows]

    await engine.dispose()

    print(f"Fetched {len(hcp_ids)} HCP IDs, {len(brands)} brands")

    # Generate months from 2025-01 to 2026-06
    months = []
    for year in (2025, 2026):
        end_month = 12 if year == 2025 else 6
        for m in range(1, end_month + 1):
            months.append(f"{year}-{m:02d}")

    # Build rows
    data_rows = []
    for _ in range(80):
        hcp_id = random.choice(hcp_ids)
        brand_id, _ = random.choice(brands)
        month = random.choice(months)
        nrx = random.randint(1, 50)
        trx = nrx + random.randint(5, 50)
        data_rows.append([hcp_id, brand_id, month, str(nrx), str(trx)])

    # Add deliberately bad rows for validation testing
    # Row with empty hcp_id
    brand_id, _ = random.choice(brands)
    data_rows.append(["", brand_id, "2025-03", "10", "20"])

    # Row with non-UUID brand_id
    data_rows.append([random.choice(hcp_ids), "not-a-uuid", "2025-04", "5", "15"])

    # Row with nrx as text
    brand_id, _ = random.choice(brands)
    data_rows.append([random.choice(hcp_ids), brand_id, "2025-05", "abc", "30"])

    # Row with future month
    brand_id, _ = random.choice(brands)
    data_rows.append([random.choice(hcp_ids), brand_id, "2027-01", "8", "25"])

    # Row with nrx > trx (logical error)
    brand_id, _ = random.choice(brands)
    data_rows.append([random.choice(hcp_ids), brand_id, "2025-06", "99", "10"])

    # CSV formula injection check: verify no cell starts with =, +, -, @
    for row_idx, row in enumerate(data_rows):
        for col_idx, cell in enumerate(row):
            if cell and cell[0] in ("=", "+", "-", "@"):
                # Prefix with single quote to neutralize formula injection
                data_rows[row_idx][col_idx] = "'" + cell

    # Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "rx_monthly_sample.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["hcp_id", "brand_id", "month", "nrx", "trx"])
        writer.writerows(data_rows)

    print(f"Wrote {len(data_rows)} rows to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
