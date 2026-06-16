#!/usr/bin/env python3
"""Load NFHS-5 at DISTRICT grain into Lakebase `nfhs_district` — the demand/coverage
layer the public-health agents reason over: childhood immunization (campaign targeting),
NCD prevalence (burden), and maternal/insurance context. nfhs_state stays the state
rollup; this is the district detail keyed to match facility_services.district.

Env: DBX_HOST, DBX_HTTP_PATH, DBX_TOKEN, LAKEBASE_URL
"""
from __future__ import annotations
import os

from databricks import sql
import psycopg

SRC = ("databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
       ".nfhs_5_district_health_indicators")

# (lakebase_col, nfhs_district_col)
IND = [
    ("full_immunization", "child_12_23m_fully_vaccinated_based_on_information_from_eit_pct"),
    ("bcg", "child_12_23m_who_have_received_bcg_pct"),
    ("penta3", "child_12_23m_who_have_received_3_doses_of_penta_or_dpt_vacc_pct"),
    ("diabetes", "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct"),
    ("hypertension", "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct"),
    ("institutional_birth", "institutional_birth_5y_pct"),
    ("insurance", "hh_member_covered_health_insurance_pct"),
    ("stunting", "child_u5_who_are_stunted_height_for_age_18_pct"),
]

DDL = """
CREATE TABLE IF NOT EXISTS nfhs_district (
    state               TEXT,
    district            TEXT,
    dkey                TEXT,   -- normalized district name, to join facility_services.district
    full_immunization   DOUBLE PRECISION,
    bcg                 DOUBLE PRECISION,
    penta3              DOUBLE PRECISION,
    diabetes            DOUBLE PRECISION,
    hypertension        DOUBLE PRECISION,
    institutional_birth DOUBLE PRECISION,
    insurance           DOUBLE PRECISION,
    stunting            DOUBLE PRECISION,
    PRIMARY KEY (state, district)
)"""


def main() -> None:
    avgs = ",\n  ".join(
        f"avg(try_cast(regexp_replace({col}, '[^0-9.]', '') AS double)) AS {name}"
        for name, col in IND)
    # dkey = upper(trim) collapse spaces — matches facility_services.district (from PIN dir)
    query = (f"SELECT trim(state_ut) AS state, trim(district_name) AS district,\n"
             f"  upper(regexp_replace(trim(district_name), '\\\\s+', ' ')) AS dkey,\n  {avgs}\n"
             f"FROM {SRC} WHERE state_ut IS NOT NULL AND district_name IS NOT NULL "
             f"AND trim(district_name) <> ''\nGROUP BY 1, 2, 3")

    conn = sql.connect(server_hostname=os.environ["DBX_HOST"], http_path=os.environ["DBX_HTTP_PATH"],
                       access_token=os.environ["DBX_TOKEN"])
    cur = conn.cursor()
    cur.execute(query)
    cols = [c[0] for c in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    print(f"read {len(rows)} districts from NFHS-5 ({len(cols)} cols)")

    url = os.environ["LAKEBASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    ph = ",".join(["%s"] * len(cols))
    upd = ",".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ("state", "district"))
    ins = (f"INSERT INTO nfhs_district ({','.join(cols)}) VALUES ({ph}) "
           f"ON CONFLICT (state, district) DO UPDATE SET {upd}")
    with psycopg.connect(url) as pg, pg.cursor() as pc:
        pc.execute(DDL)
        pc.execute("CREATE INDEX IF NOT EXISTS ix_nd_dkey ON nfhs_district (dkey)")
        pc.executemany(ins, rows)
        pg.commit()
        # how well do NFHS districts line up with the facilities' (PIN-derived) districts?
        pc.execute("SELECT count(DISTINCT fs.district) FROM facility_services fs "
                   "JOIN nfhs_district nd ON nd.dkey = fs.district WHERE fs.district IS NOT NULL")
        joined = pc.fetchone()[0]
    print(f"loaded {len(rows)} districts into nfhs_district · {joined} match facility_services.district")


if __name__ == "__main__":
    main()
