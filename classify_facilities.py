#!/usr/bin/env python3
"""Classify each facility into clinical service lines + capacity → Lakebase
`facility_services`. Deterministic (app/taxonomy.py): which of the 7 categories a
provider covers (from its specialties + procedures), its bed capacity (total +
per-category where the text states it), and the data-readiness completeness flags
(a hospital with no bed count; a provider with no specialty).

Env: DBX_HOST, DBX_HTTP_PATH, DBX_TOKEN, LAKEBASE_URL
"""
from __future__ import annotations
import json
import os
import re
import sys

from databricks import sql
import psycopg
from psycopg.types.json import Json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import taxonomy as tax  # noqa: E402

SRC = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities"
SEL = ("unique_id, facilityTypeId, address_city, address_stateOrRegion, address_zipOrPostcode, "
       "specialties, procedure, capability, description, capacity, numberDoctors, source_urls")
# bed counts are only meaningful for inpatient facility types
INPATIENT = {"hospital", "medicalcollege", "nursinghome", "medicalcenter"}

DDL = """
CREATE TABLE IF NOT EXISTS facility_services (
    facility_id       TEXT PRIMARY KEY,
    facility_type     TEXT,
    city              TEXT,
    state             TEXT,
    postcode          TEXT,
    total_beds        INTEGER,
    n_doctors         INTEGER,
    n_categories      INTEGER,
    n_sources         INTEGER,      -- corroborating source URLs (cardinality)
    services          JSONB,        -- {category: {specialties, procedures, beds, offered}}
    cap_specialists   JSONB,        -- {capability: n_relevant_specialists} (the cross-check)
    missing_beds      BOOLEAN,      -- inpatient facility with no stated bed count
    missing_specialty BOOLEAN       -- a provider with no specialty attached
)"""


def parse_arr(s: str | None) -> list[str]:
    if not s:
        return []
    try:
        a = json.loads(s)
        return [x for x in a if isinstance(x, str) and x.strip()] if isinstance(a, list) else []
    except Exception:  # noqa: BLE001 — dirty / non-JSON values exist
        return []


def to_int(s, hi: int = 100000) -> int | None:
    """First integer in the value, or None — and None if implausibly large
    (junk like a leaked coordinate/phone in the capacity field)."""
    if s is None:
        return None
    m = re.search(r"\d+", str(s).replace(",", ""))
    if not m:
        return None
    v = int(m.group())
    return v if 0 <= v <= hi else None


def main() -> None:
    conn = sql.connect(server_hostname=os.environ["DBX_HOST"], http_path=os.environ["DBX_HTTP_PATH"],
                       access_token=os.environ["DBX_TOKEN"])
    cur = conn.cursor()
    cur.execute(f"SELECT {SEL} FROM {SRC}")
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close(); conn.close()
    print(f"read {len(rows)} facilities")

    out = []
    for r in rows:
        d = dict(zip(cols, r))
        specs, procs = parse_arr(d["specialties"]), parse_arr(d["procedure"])
        svc = {c: {"specialties": 0, "procedures": 0, "beds": 0, "offered": False} for c in tax.CATEGORIES}
        for s in specs:
            svc[tax.classify_specialty(s)]["specialties"] += 1
        for p in procs:
            svc[tax.classify_procedure(p)]["procedures"] += 1
        text = " ".join(filter(None, [d.get("description"), d.get("capability"), d.get("procedure")]))
        for cat, n in tax.extract_category_beds(text).items():
            svc[cat]["beds"] += n
        for c in tax.CATEGORIES:
            svc[c]["offered"] = svc[c]["specialties"] > 0 or svc[c]["procedures"] > 0
        n_cat = sum(1 for c in tax.CATEGORIES if svc[c]["offered"])
        cap_spec = tax.count_capability_specialists(specs)
        n_sources = len(parse_arr(d["source_urls"]))
        total_beds, n_doctors = to_int(d["capacity"]), to_int(d["numberDoctors"])
        ftype = (d["facilityTypeId"] or "").lower()
        clean = lambda v: v.replace("\x00", "") if isinstance(v, str) else v  # noqa: E731
        out.append((
            d["unique_id"], d["facilityTypeId"] or "", clean(d["address_city"]),
            clean(d["address_stateOrRegion"]), clean(d["address_zipOrPostcode"]),
            total_beds, n_doctors, n_cat, n_sources, Json(svc), Json(cap_spec),
            ftype in INPATIENT and not total_beds, len(specs) == 0))

    url = os.environ["LAKEBASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    cols2 = ["facility_id", "facility_type", "city", "state", "postcode", "total_beds",
             "n_doctors", "n_categories", "n_sources", "services", "cap_specialists",
             "missing_beds", "missing_specialty"]
    ph = ",".join(["%s"] * len(cols2))
    upd = ",".join(f"{c}=EXCLUDED.{c}" for c in cols2 if c != "facility_id")
    ins = (f"INSERT INTO facility_services ({','.join(cols2)}) VALUES ({ph}) "
           f"ON CONFLICT (facility_id) DO UPDATE SET {upd}")
    with psycopg.connect(url) as pg, pg.cursor() as pc:
        pc.execute(DDL)
        pc.execute("ALTER TABLE facility_services ADD COLUMN IF NOT EXISTS n_sources INTEGER")
        pc.execute("ALTER TABLE facility_services ADD COLUMN IF NOT EXISTS cap_specialists JSONB")
        for i in range(0, len(out), 500):
            pc.executemany(ins, out[i:i + 500])
            pg.commit()
    print(f"classified {len(out)} facilities into facility_services")
    with psycopg.connect(url) as pg, pg.cursor() as pc:
        pc.execute("SELECT count(*) FILTER (WHERE missing_beds), count(*) FILTER (WHERE missing_specialty), "
                   "count(*) FILTER (WHERE total_beds>0) FROM facility_services")
        mb, ms, tb = pc.fetchone()
        print(f"  inpatient facilities missing a bed count: {mb} · providers missing specialty: {ms} · with beds: {tb}")


if __name__ == "__main__":
    main()
