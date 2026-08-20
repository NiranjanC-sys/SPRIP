"""Time database queries to find the bottleneck in /events endpoint."""
import time
import psycopg

conn = psycopg.connect("postgresql://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi")
cur = conn.cursor()
cur.execute("SET app.tenant_id = 'cf36db2e-3d7f-47a1-8d16-6f483009ba9c'")

# Simple count
t0 = time.time()
cur.execute("SELECT count(*) FROM core.events WHERE status != 'CANCELLED'")
print(f"COUNT events: {cur.fetchone()[0]}, took {(time.time()-t0)*1000:.0f}ms")

# SELECT with LIMIT
t0 = time.time()
cur.execute(
    "SELECT id, name, event_date, status FROM core.events "
    "WHERE status != 'CANCELLED' ORDER BY event_date DESC, id DESC LIMIT 51"
)
rows = cur.fetchall()
print(f"SELECT 51 events: {len(rows)} rows, took {(time.time()-t0)*1000:.0f}ms")

# With brand join
t0 = time.time()
cur.execute(
    "SELECT e.id, e.name, e.event_date, e.status, b.name "
    "FROM core.events e LEFT JOIN core.brands b ON b.id = e.brand_id "
    "WHERE e.status != 'CANCELLED' ORDER BY e.event_date DESC, e.id DESC LIMIT 51"
)
rows = cur.fetchall()
print(f"SELECT with brand join: {len(rows)} rows, took {(time.time()-t0)*1000:.0f}ms")

# Speaker count subquery
t0 = time.time()
cur.execute(
    "SELECT es.event_id, count(*) FROM core.event_speakers es "
    "WHERE es.event_id IN (SELECT id FROM core.events WHERE status != 'CANCELLED' LIMIT 51) "
    "GROUP BY es.event_id"
)
rows = cur.fetchall()
print(f"Speaker counts for 51 events: {len(rows)} rows, took {(time.time()-t0)*1000:.0f}ms")

# EXPLAIN ANALYZE
cur.execute(
    "EXPLAIN ANALYZE SELECT id, name, event_date, status FROM core.events "
    "WHERE status != 'CANCELLED' ORDER BY event_date DESC, id DESC LIMIT 51"
)
print("\nEXPLAIN ANALYZE:")
for row in cur.fetchall():
    print(f"  {row[0]}")

conn.close()
