"""Run each demo query and print results."""
import os, re, duckdb

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = DB = os.path.join(ROOT, "speaker_roi.duckdb")
SQL = os.path.join(ROOT, "demo_queries.sql")

con = duckdb.connect(DB, read_only=True)

with open(SQL, "r", encoding="utf-8") as f:
    raw = f.read()

# Split on blank-line-separated queries; keep the leading comment as the title
blocks = re.split(r"\n{2,}(?=--\s*\d+\.)", raw.strip())

for i, block in enumerate(blocks, 1):
    lines = block.strip().splitlines()
    title_lines = [l for l in lines if l.startswith("--")]
    title = " ".join(l.lstrip("- ").strip() for l in title_lines[:1])
    sql = "\n".join(l for l in lines if not l.startswith("--")).strip().rstrip(";")
    if not sql:
        continue
    print(f"\n{'='*72}")
    print(f"QUERY {i}: {title}")
    print(f"{'='*72}")
    try:
        result = con.execute(sql).fetchdf()
        print(result.to_string(index=False))
    except Exception as e:
        print(f"ERROR: {e}")

con.close()
