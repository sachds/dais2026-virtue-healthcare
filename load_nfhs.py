#!/usr/bin/env python3
"""Load NFHS-5 district health indicators, aggregated to state, into Lakebase.

This is the demand-side overlay for Track 2: it lets the gap map turn "where is
there no trusted supply" into "where is the dangerous shortfall" — a confirmed
supply gap sitting in a state with high health burden / low coverage.

Source values are fact-sheet strings: '*' = suppressed, '(29.5)' = estimate on a
small base. We keep digits and dots only (`regexp_replace(col,'[^0-9.]','')`) and
`try_cast` to double, so suppressed/blank cells become NULL and avg() skips them.

Env: DBX_HOST, DBX_HTTP_PATH, DBX_TOKEN, LAKEBASE_URL
"""
from __future__ import annotations
import os
from databricks import sql
import psycopg

SRC = ("databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
       ".nfhs_5_district_health_indicators")

# (lakebase_col, nfhs_district_col) — averaged across a state's districts.
IND = [
    ("institutional_birth", "institutional_birth_5y_pct"),
    ("anc4", "mothers_who_had_at_least_4_anc_visits_lb5y_pct"),
    ("csection", "births_delivered_by_csection_5y_pct"),
    ("insurance", "hh_member_covered_health_insurance_pct"),
    ("stunting", "child_u5_who_are_stunted_height_for_age_18_pct"),
]

DDL = """
CREATE TABLE IF NOT EXISTS nfhs_state (
    state                 TEXT PRIMARY KEY,
    institutional_birth   DOUBLE PRECISION,
    anc4                  DOUBLE PRECISION,
    csection              DOUBLE PRECISION,
    insurance             DOUBLE PRECISION,
    stunting              DOUBLE PRECISION,
    n_districts           INTEGER
)"""


def main() -> None:
    avgs = ",\n  ".join(
        f"avg(try_cast(regexp_replace({col}, '[^0-9.]', '') AS double)) AS {name}"
        for name, col in IND)
    query = (f"SELECT trim(state_ut) AS state,\n  {avgs},\n  count(*) AS n_districts\n"
             f"FROM {SRC} WHERE state_ut IS NOT NULL AND trim(state_ut) <> ''\n"
             f"GROUP BY trim(state_ut) ORDER BY state")

    conn = sql.connect(
        server_hostname=os.environ["DBX_HOST"],
        http_path=os.environ["DBX_HTTP_PATH"],
        access_token=os.environ["DBX_TOKEN"],
    )
    cur = conn.cursor()
    cur.execute(query)
    cols = [c[0] for c in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    print(f"aggregated {len(rows)} states from NFHS-5 ({len(cols)} cols)")

    url = os.environ["LAKEBASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    placeholders = ",".join(["%s"] * len(cols))
    updates = ",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "state")
    ins = (f"INSERT INTO nfhs_state ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT (state) DO UPDATE SET {updates}")

    with psycopg.connect(url) as pg, pg.cursor() as pc:
        pc.execute(DDL)
        pc.executemany(ins, rows)
        pg.commit()
    print(f"loaded {len(rows)} states into Lakebase nfhs_state")
    # show a few of the highest-need states (low institutional birth)
    with psycopg.connect(url) as pg, pg.cursor() as pc:
        pc.execute("SELECT state, round(institutional_birth::numeric,1), "
                   "round(insurance::numeric,1), round(stunting::numeric,1), n_districts "
                   "FROM nfhs_state ORDER BY institutional_birth NULLS LAST LIMIT 6")
        print("  lowest institutional-birth states (inst%, ins%, stunt%, districts):")
        for r in pc.fetchall():
            print("   ", r)


if __name__ == "__main__":
    main()
