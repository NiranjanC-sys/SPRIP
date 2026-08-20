"""
=============================================================================
 Speaker Program Impact / ROI — Database Load Script
 Loads bronze/, silver/conformed/, and gold/ CSVs into DuckDB.
 Repeatable: drops and recreates all tables on each run.
=============================================================================
"""

from __future__ import annotations

import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(ROOT)
DB_PATH = os.path.join(PROJECT, "speaker_roi.duckdb")
BRONZE = os.path.join(PROJECT, "data", "bronze")
SILVER_CONF = os.path.join(PROJECT, "data", "silver", "conformed")
GOLD = os.path.join(PROJECT, "data", "gold")
SCHEMA_SQL = os.path.join(ROOT, "schema.sql")

# ---- CSV -> table mapping ---------------------------------------------------

BRONZE_TABLES = [
    ("hcp_master",          "hcp_master.csv"),
    ("events",              "events.csv"),
    ("event_invitations",   "event_invitations.csv"),
    ("event_attendance",    "event_attendance.csv"),
    ("hcp_rx_monthly",      "hcp_rx_monthly.csv"),
    ("marketing_activity",  "marketing_activity.csv"),
    ("event_cost",          "event_cost.csv"),
    ("market_factors",      "market_factors.csv"),
    ("identity_crosswalk",  "identity_crosswalk.csv"),
    ("business_assumptions","business_assumptions.csv"),
    ("ground_truth",        "ground_truth.csv"),
]

SILVER_TABLES = [
    ("hcp_master",          "hcp_master.csv"),
    ("events",              "events.csv"),
    ("event_invitations",   "event_invitations.csv"),
    ("event_attendance",    "event_attendance.csv"),
    ("hcp_rx_monthly",      "hcp_rx_monthly.csv"),
    ("marketing_activity",  "marketing_activity.csv"),
    ("event_cost",          "event_cost.csv"),
    ("market_factors",      "market_factors.csv"),
    ("identity_crosswalk",  "identity_crosswalk.csv"),
    ("business_assumptions","business_assumptions.csv"),
]

GOLD_TABLES = [
    ("eligibility_table",   "eligibility_table.csv"),
    ("eligibility_summary", "eligibility_summary.csv"),
]


def load_csv_via_staging(con: duckdb.DuckDBPyConnection,
                         schema: str, table: str, csv_path: str):
    """Load a CSV into a target table using a temporary staging table to handle
    type coercion and column-name quoting automatically."""
    fqn = f"{schema}.{table}"
    stg = f"__stg_{schema}_{table}"

    con.execute(f"DROP TABLE IF EXISTS {stg}")
    con.execute(f"""
        CREATE TEMP TABLE {stg} AS
        SELECT * FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)
    """)

    cols = [r[0] for r in con.execute(f"DESCRIBE {fqn}").fetchall()]
    col_types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {fqn}").fetchall()}

    select_parts = []
    for c in cols:
        src_col = f'"{c}"'
        tgt_type = col_types[c]

        if "BOOLEAN" in tgt_type.upper():
            select_parts.append(
                f"CASE WHEN {src_col} IN ('True','true','1') THEN TRUE "
                f"WHEN {src_col} IN ('False','false','0') THEN FALSE "
                f"WHEN {src_col} IS NULL OR {src_col} = '' THEN NULL "
                f"END AS \"{c}\""
            )
        elif "DATE" in tgt_type.upper() and "VARCHAR" not in tgt_type.upper():
            select_parts.append(f"TRY_CAST({src_col} AS DATE) AS \"{c}\"")
        elif "INTEGER" in tgt_type.upper() or "INT" in tgt_type.upper():
            select_parts.append(f"TRY_CAST({src_col} AS INTEGER) AS \"{c}\"")
        elif "NUMERIC" in tgt_type.upper() or "DECIMAL" in tgt_type.upper():
            select_parts.append(f"TRY_CAST({src_col} AS {tgt_type}) AS \"{c}\"")
        else:
            select_parts.append(f"NULLIF({src_col}, '') AS \"{c}\"")

    insert_sql = f"""
        INSERT INTO {fqn} ({', '.join(f'"{c}"' for c in cols)})
        SELECT {', '.join(select_parts)}
        FROM {stg}
    """
    con.execute(insert_sql)
    con.execute(f"DROP TABLE IF EXISTS {stg}")


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing database: {DB_PATH}")

    con = duckdb.connect(DB_PATH)
    print(f"Created database: {DB_PATH}\n")

    # ---- Execute DDL --------------------------------------------------------
    print("Executing schema.sql ...")
    with open(SCHEMA_SQL, "r", encoding="utf-8") as f:
        ddl = f.read()
    # Strip single-line comments, then split on semicolons
    import re
    ddl_clean = re.sub(r"--[^\n]*", "", ddl)
    for stmt in ddl_clean.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    print("    Schemas and tables created.\n")

    # ---- Load bronze --------------------------------------------------------
    print("Loading BRONZE tables ...")
    for table, csv_file in BRONZE_TABLES:
        csv_path = os.path.join(BRONZE, csv_file).replace("\\", "/")
        load_csv_via_staging(con, "bronze", table, csv_path)
        cnt = con.execute(f"SELECT COUNT(*) FROM bronze.{table}").fetchone()[0]
        print(f"    bronze.{table:25s} {cnt:>8,} rows")

    # ---- Load silver (order matters for FK: hcp_master, events first) --------
    print("\nLoading SILVER tables ...")
    ordered_silver = [
        ("hcp_master", "hcp_master.csv"),
        ("events", "events.csv"),
    ] + [(t, f) for t, f in SILVER_TABLES if t not in ("hcp_master", "events")]

    for table, csv_file in ordered_silver:
        csv_path = os.path.join(SILVER_CONF, csv_file).replace("\\", "/")
        load_csv_via_staging(con, "silver", table, csv_path)
        cnt = con.execute(f"SELECT COUNT(*) FROM silver.{table}").fetchone()[0]
        print(f"    silver.{table:25s} {cnt:>8,} rows")

    # ---- Load gold (eligibility_table, eligibility_summary) ------------------
    print("\nLoading GOLD tables ...")
    for table, csv_file in GOLD_TABLES:
        csv_path = os.path.join(GOLD, csv_file).replace("\\", "/")
        load_csv_via_staging(con, "gold", table, csv_path)
        cnt = con.execute(f"SELECT COUNT(*) FROM gold.{table}").fetchone()[0]
        print(f"    gold.{table:25s} {cnt:>8,} rows")

    # ---- Verification -------------------------------------------------------
    print("\n" + "=" * 60)
    print("VERIFICATION — row counts across all schemas")
    print("=" * 60)

    expected = {
        "bronze.hcp_master": 2500,
        "bronze.events": 300,
        "bronze.event_invitations": 28331,
        "bronze.event_attendance": 9926,
        "bronze.hcp_rx_monthly": 207596,
        "bronze.marketing_activity": 80000,
        "bronze.event_cost": 300,
        "bronze.market_factors": 224,
        "bronze.identity_crosswalk": 2500,
        "bronze.business_assumptions": 12,
        "bronze.ground_truth": 5033,
        "silver.hcp_master": 2375,
        "silver.events": 300,
        "silver.event_invitations": 23137,
        "silver.event_attendance": 8941,
        "silver.hcp_rx_monthly": 197492,
        "silver.marketing_activity": 76000,
        "silver.event_cost": 300,
        "silver.market_factors": 224,
        "silver.identity_crosswalk": 2375,
        "silver.business_assumptions": 12,
        "gold.eligibility_table": 23137,
        "gold.eligibility_summary": 262,
    }

    all_ok = True
    for fqn, exp in expected.items():
        schema, table = fqn.split(".")
        actual = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]
        status = "OK" if actual == exp else "MISMATCH"
        if status != "OK":
            all_ok = False
        print(f"    {fqn:40s}  expected={exp:>8,}  actual={actual:>8,}  {status}")

    print("\n" + ("ALL COUNTS MATCH" if all_ok else "*** MISMATCHES DETECTED ***"))

    con.close()
    print(f"\nDatabase ready: {DB_PATH}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
