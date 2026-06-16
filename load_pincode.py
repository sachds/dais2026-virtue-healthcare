#!/usr/bin/env python3
"""Load the India Post PIN directory → Lakebase `pincode` (PIN → district → state),
then stamp each facility's district onto `facility_services` via its postcode.

This is the geography bridge: facilities carry a PIN (address_zipOrPostcode) but no
district; NFHS-5 and 'local provider' both live at the district grain. One PIN can
host several post offices (and rarely span districts) — we keep the modal district.

Env: DBX_HOST, DBX_HTTP_PATH, DBX_TOKEN, LAKEBASE_URL
"""
from __future__ import annotations
import os

from databricks import sql
import psycopg

SRC = ("databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
       ".india_post_pincode_directory")

QUERY = f"""
WITH d AS (
  SELECT lpad(cast(cast(pincode AS int) AS string), 6, '0') AS pin,
         trim(district) AS district, trim(statename) AS state, count(*) AS c
  FROM {SRC}
  WHERE pincode IS NOT NULL AND district IS NOT NULL AND trim(district) <> ''
  GROUP BY 1, 2, 3
),
r AS (SELECT pin, district, state, row_number() OVER (PARTITION BY pin ORDER BY c DESC) rn FROM d)
SELECT pin AS pincode, district, state FROM r WHERE rn = 1
"""

DDL = """
CREATE TABLE IF NOT EXISTS pincode (
    pincode  TEXT PRIMARY KEY,
    district TEXT,
    state    TEXT
)"""


def main() -> None:
    conn = sql.connect(server_hostname=os.environ["DBX_HOST"], http_path=os.environ["DBX_HTTP_PATH"],
                       access_token=os.environ["DBX_TOKEN"])
    cur = conn.cursor()
    cur.execute(QUERY)
    rows = [list(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    print(f"resolved {len(rows)} PINs → district")

    url = os.environ["LAKEBASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as pg, pg.cursor() as pc:
        pc.execute(DDL)
        pc.execute("ALTER TABLE facility_services ADD COLUMN IF NOT EXISTS district TEXT")
        ins = "INSERT INTO pincode (pincode,district,state) VALUES (%s,%s,%s) ON CONFLICT (pincode) DO UPDATE SET district=EXCLUDED.district, state=EXCLUDED.state"
        for i in range(0, len(rows), 1000):
            pc.executemany(ins, rows[i:i + 1000])
        pg.commit()
        print(f"loaded {len(rows)} pincodes into Lakebase")
        # stamp district onto facilities via their normalized 6-digit postcode
        pc.execute("CREATE INDEX IF NOT EXISTS ix_fs_district ON facility_services (district)")
        pc.execute("""UPDATE facility_services fs SET district = p.district
                      FROM pincode p
                      WHERE lpad(regexp_replace(coalesce(fs.postcode,''), '[^0-9]', ''), 6, '0') = p.pincode
                        AND fs.postcode IS NOT NULL AND fs.postcode <> ''""")
        pg.commit()
        pc.execute("SELECT count(*) FILTER (WHERE district IS NOT NULL), count(*) FROM facility_services")
        matched, total = pc.fetchone()
        pc.execute("SELECT count(DISTINCT district) FROM facility_services WHERE district IS NOT NULL")
        ndist = pc.fetchone()[0]
    print(f"stamped district on {matched}/{total} facilities across {ndist} districts "
          f"({round(100*matched/total)}% matched)")


if __name__ == "__main__":
    main()
