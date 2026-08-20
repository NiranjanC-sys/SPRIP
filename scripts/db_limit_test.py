"""Test if small LIMIT values cause slow queries through RLS."""
import time
import psycopg

conn = psycopg.connect("postgresql://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi")
cur = conn.cursor()
cur.execute("SET app.tenant_id = 'cf36db2e-3d7f-47a1-8d16-6f483009ba9c'")

for lim in [2, 6, 11, 51]:
    t0 = time.time()
    cur.execute(f"""
        SELECT e.id, e.code, e.name, e.brand_id, e.event_date, e.status
        FROM core.events e
        WHERE e.status != 'CANCELLED'
        ORDER BY e.event_date DESC, e.id DESC
        LIMIT {lim}
    """)
    rows = cur.fetchall()
    print(f"LIMIT {lim}: {len(rows)} rows, {(time.time()-t0)*1000:.1f}ms")

# Now test with selectinload equivalent
print("\n--- With brand subquery ---")
for lim in [2, 6, 51]:
    t0 = time.time()
    cur.execute(f"""
        SELECT e.id, e.code, e.name, e.brand_id, e.event_date, e.status
        FROM core.events e
        WHERE e.status != 'CANCELLED'
        ORDER BY e.event_date DESC, e.id DESC
        LIMIT {lim}
    """)
    event_ids = [r[0] for r in cur.fetchall()]

    # Brand fetch (selectinload)
    if event_ids:
        cur.execute("SELECT id, name FROM core.brands WHERE id IN %s", (tuple(set(r for r in event_ids)),))
        cur.fetchall()

    # Speaker counts
    if event_ids:
        cur.execute("""
            SELECT event_id, count(*) FROM core.event_speakers
            WHERE event_id IN %s GROUP BY event_id
        """, (tuple(event_ids),))
        cur.fetchall()

    print(f"LIMIT {lim} full: {(time.time()-t0)*1000:.1f}ms")

# Check if it's the Pydantic serialization
print("\n--- EXPLAIN ANALYZE for LIMIT 2 ---")
cur.execute("""
    EXPLAIN ANALYZE SELECT e.id, e.code, e.name, e.brand_id, e.event_date, e.status
    FROM core.events e
    WHERE e.status != 'CANCELLED'
    ORDER BY e.event_date DESC, e.id DESC
    LIMIT 2
""")
for row in cur.fetchall():
    print(f"  {row[0]}")

conn.close()
