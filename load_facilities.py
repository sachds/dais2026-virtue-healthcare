#!/usr/bin/env python3
"""Load Virtue Foundation facilities from the Delta Sharing catalog into Lakebase.

Reads the shared Delta table via a SQL warehouse and upserts the curated columns
into the Lakebase `facilities` table (batched).

Env: DBX_HOST, DBX_HTTP_PATH, DBX_TOKEN, LAKEBASE_URL
"""
from __future__ import annotations
import os
from databricks import sql
import psycopg

SRC = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities"

# (lakebase_col, delta_expr)
COLS = [
    ("id", "unique_id"), ("name", "name"), ("organization_type", "organization_type"),
    ("facility_type", "facilityTypeId"), ("operator_type", "operatorTypeId"),
    ("city", "address_city"), ("state", "address_stateOrRegion"), ("postcode", "address_zipOrPostcode"),
    ("latitude", "latitude"), ("longitude", "longitude"),
    ("description", "description"), ("specialties", "specialties"), ("procedure", "procedure"),
    ("equipment", "equipment"), ("capability", "capability"),
    ("number_doctors", "numberDoctors"), ("capacity", "capacity"), ("year_established", "yearEstablished"),
    ("websites", "websites"), ("official_website", "officialWebsite"),
    ("source_urls", "source_urls"), ("source", "source"),
    ("phone", "officialPhone"), ("email", "email"),
]


def main() -> None:
    select_exprs = ", ".join(f"{expr} AS {col}" for col, expr in COLS)
    conn = sql.connect(
        server_hostname=os.environ["DBX_HOST"],
        http_path=os.environ["DBX_HTTP_PATH"],
        access_token=os.environ["DBX_TOKEN"],
    )
    cur = conn.cursor()
    cur.execute(f"SELECT {select_exprs} FROM {SRC}")
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close(); conn.close()
    print(f"read {len(rows)} facilities from Delta ({len(cols)} cols)")

    url = os.environ["LAKEBASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    placeholders = ",".join(["%s"] * len(cols))
    updates = ",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id")
    ins = (f"INSERT INTO facilities ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT (id) DO UPDATE SET {updates}")

    # Postgres text cannot hold NUL (0x00) bytes; strip them.
    def clean(r):
        return [v.replace("\x00", "") if isinstance(v, str) else v for v in r]

    sanitized = [clean(r) for r in rows]
    with psycopg.connect(url) as pg, pg.cursor() as pc:
        for i in range(0, len(sanitized), 500):
            pc.executemany(ins, sanitized[i:i + 500])
            pg.commit()
            print(f"  upserted {min(i + 500, len(sanitized))}")
    print(f"loaded {len(rows)} facilities into Lakebase")


if __name__ == "__main__":
    main()
