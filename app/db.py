"""Data layer for the Facility Trust Desk. Reads facilities + precomputed trust
signals from Lakebase, and persists analyst reviews (overrides/notes/shortlists)."""
from __future__ import annotations

import json
import os
import re
import time
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

CAPS = ["icu", "maternity", "emergency", "oncology", "trauma", "nicu"]
SIGNAL_RANK = {"strong": 3, "partial": 2, "weak": 1, "none": 0}


def conninfo() -> str:
    url = os.environ.get("LAKEBASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url.replace("postgresql+psycopg://", "postgresql://").replace(
            "postgres+psycopg://", "postgresql://"
        )
    if os.environ.get("PGHOST"):  # Databricks Apps + Lakebase resource binding
        return ""
    return "postgresql://commons_app@localhost:5432/databricks_postgres"


def _conn():
    return psycopg.connect(conninfo(), row_factory=dict_row)


def now() -> int:
    return int(time.time())


# --------------------------------------------------------------------------- #
def states() -> list[str]:
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT DISTINCT state FROM facilities WHERE state IS NOT NULL ORDER BY state")
        return [r["state"] for r in cur.fetchall()]


def overview() -> dict:
    """Counts by capability × signal — for the planner's at-a-glance dashboard."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT capability, signal, count(*) n FROM trust_signals
               GROUP BY capability, signal"""
        )
        grid = {cap: {"strong": 0, "partial": 0, "weak": 0, "none": 0} for cap in CAPS}
        for r in cur.fetchall():
            grid.setdefault(r["capability"], {}).update({r["signal"]: r["n"]})
        cur.execute("SELECT count(*) n FROM facilities")
        n_fac = cur.fetchone()["n"]
        cur.execute("SELECT count(DISTINCT facility_id) n FROM trust_signals")
        n_scored = cur.fetchone()["n"]
    return {"grid": grid, "facilities": n_fac, "scored": n_scored, "caps": CAPS}


def list_facilities(q: str = "", state: str = "", capability: str = "",
                    signal: str = "", limit: int = 40) -> list[dict]:
    """Search/browse. With a capability filter, returns that capability's signal +
    evidence count per facility (the Referral-Copilot-style entry point)."""
    where, args = ["1=1"], []
    if q:
        where.append("(f.name ILIKE %s OR f.city ILIKE %s OR f.state ILIKE %s)")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if state:
        where.append("f.state = %s"); args.append(state)

    if capability:
        sql = f"""
          SELECT f.id, f.name, f.city, f.state, f.facility_type, f.operator_type,
                 t.signal, t.confidence, t.rationale,
                 jsonb_array_length(coalesce(t.evidence,'[]'::jsonb)) AS n_evidence
          FROM facilities f JOIN trust_signals t
               ON t.facility_id = f.id AND t.capability = %s
          WHERE {' AND '.join(where)} {('AND t.signal = %s' if signal else '')}
          ORDER BY CASE t.signal WHEN 'strong' THEN 3 WHEN 'partial' THEN 2
                                 WHEN 'weak' THEN 1 ELSE 0 END DESC, t.confidence DESC
          LIMIT %s"""
        args = [capability] + args + ([signal] if signal else []) + [limit]
    else:
        sql = f"""
          SELECT f.id, f.name, f.city, f.state, f.facility_type, f.operator_type,
                 (SELECT count(*) FROM trust_signals t WHERE t.facility_id=f.id AND t.signal='strong') AS n_strong,
                 (SELECT count(*) FROM trust_signals t WHERE t.facility_id=f.id AND t.signal='partial') AS n_partial
          FROM facilities f
          WHERE {' AND '.join(where)}
          ORDER BY n_strong DESC, n_partial DESC, f.name
          LIMIT %s"""
        args = args + [limit]

    with _conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def get_facility(fid: str) -> dict | None:
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM facilities WHERE id = %s", (fid,))
        fac = cur.fetchone()
        if not fac:
            return None
        fac.pop("raw", None)
        cur.execute(
            "SELECT capability, signal, confidence, evidence, rationale, model "
            "FROM trust_signals WHERE facility_id = %s", (fid,))
        signals = {r["capability"]: r for r in cur.fetchall()}
        # latest analyst override per capability + notes/decisions
        cur.execute(
            """SELECT DISTINCT ON (capability) capability, new_signal, created_at
               FROM reviews WHERE facility_id=%s AND action='override' AND capability IS NOT NULL
               ORDER BY capability, created_at DESC""", (fid,))
        overrides = {r["capability"]: r["new_signal"] for r in cur.fetchall()}
        cur.execute(
            "SELECT action, capability, new_signal, body, user_id, created_at FROM reviews "
            "WHERE facility_id=%s AND action IN ('note','decision','override') ORDER BY created_at DESC LIMIT 50",
            (fid,))
        history = cur.fetchall()
    # cardinality cross-check: how many relevant specialists / physicians / sources
    # corroborate each claimed capability (separate connection so a missing table can't
    # abort the main read).
    fs = None
    try:
        with _conn() as c2, c2.cursor() as cur2:
            cur2.execute("SELECT n_doctors, n_sources, total_beds, cap_specialists "
                         "FROM facility_services WHERE facility_id=%s", (fid,))
            fs = cur2.fetchone()
    except Exception:  # noqa: BLE001 — table may not be loaded yet
        fs = None
    caps = []
    for cap in CAPS:
        s = signals.get(cap, {"capability": cap, "signal": "none", "confidence": 0,
                              "evidence": [], "rationale": "", "model": None})
        s["override"] = overrides.get(cap)
        if fs:
            spec = (fs["cap_specialists"] or {}).get(cap, 0)
            s["cardinality"] = {"specialists": spec, "doctors": fs["n_doctors"],
                                "sources": fs["n_sources"], "beds": fs["total_beds"],
                                "level": "high" if spec >= 3 else ("medium" if spec >= 1 else "low")}
        caps.append(s)
    return {"facility": fac, "capabilities": caps, "history": history}


def record_review(action: str, facility_id: str | None = None, capability: str | None = None,
                  new_signal: str | None = None, body: str | None = None,
                  shortlist: str | None = None, user_id: str = "planner") -> dict:
    rid = "rev_" + uuid.uuid4().hex[:14]
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO reviews (id, created_at, user_id, facility_id, capability,
                   action, new_signal, body, shortlist)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (rid, now(), user_id, facility_id, capability, action, new_signal, body, shortlist))
        row = cur.fetchone(); c.commit()
        return row


def shortlist(name: str = "default") -> list[dict]:
    """Current shortlist = facilities added and not later removed (append-only, latest wins)."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (facility_id) facility_id, action, body, created_at
               FROM reviews WHERE shortlist=%s AND action IN ('shortlist','unshortlist')
               ORDER BY facility_id, created_at DESC""", (name,))
        ids = [r["facility_id"] for r in cur.fetchall() if r["action"] == "shortlist"]
        if not ids:
            return []
        cur.execute("SELECT id, name, city, state FROM facilities WHERE id = ANY(%s)", (ids,))
        return cur.fetchall()


def copilot_candidates(caps: list[str], location: str = "", limit: int = 8) -> list[dict]:
    """The Copilot's retrieval tool: facilities in `location` that have supporting
    evidence for the requested capabilities, ranked by best trust signal."""
    caps = [c for c in caps if c in CAPS] or CAPS
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT f.id, f.name, f.city, f.state, f.facility_type,
                   jsonb_object_agg(t.capability, jsonb_build_object(
                       'signal', t.signal, 'confidence', t.confidence,
                       'evidence', t.evidence, 'rationale', t.rationale))
                     FILTER (WHERE t.capability = ANY(%(caps)s)) AS sigs,
                   max(CASE t.signal WHEN 'strong' THEN 3 WHEN 'partial' THEN 2
                                     WHEN 'weak' THEN 1 ELSE 0 END)
                     FILTER (WHERE t.capability = ANY(%(caps)s)) AS best,
                   count(*) FILTER (WHERE t.capability = ANY(%(caps)s) AND t.signal='strong') AS n_strong
            FROM facilities f JOIN trust_signals t ON t.facility_id = f.id
            WHERE (%(loc)s = '' OR f.city ILIKE %(locpat)s OR f.state ILIKE %(locpat)s)
            GROUP BY f.id, f.name, f.city, f.state, f.facility_type
            HAVING bool_or(t.capability = ANY(%(caps)s) AND t.signal IN ('strong','partial','weak'))
            ORDER BY best DESC NULLS LAST, n_strong DESC
            LIMIT %(limit)s
            """,
            {"caps": caps, "loc": location.strip(), "locpat": f"%{location.strip()}%", "limit": limit})
        return cur.fetchall()


MIN_COVERAGE = 8  # facilities we must have evaluated before calling 0-supply a confirmed gap


def _gap_status(trusted: int, n_scored: int) -> str:
    if trusted >= 1:
        return "served"        # at least one facility with strong/partial evidence
    if n_scored >= MIN_COVERAGE:
        return "gap"           # evaluated enough and found nothing trusted = confirmed desert
    return "datapoor"          # too little data to call it — distinct from a real gap


# NFHS state_ut and facility `state` are both dirty; normalize to a shared join key.
_STATE_ALIAS = {
    "maharastra": "maharashtra",   # NFHS misspelling vs facility "Maharashtra"
    "nctofdelhi": "delhi",
    "orissa": "odisha",
    "uttaranchal": "uttarakhand",
    "pondicherry": "puducherry",
}


def _norm_state(s: str | None) -> str:
    s = (s or "").strip().lower().replace("&", "and")
    s = re.sub(r"[^a-z]", "", s)   # drop spaces, punctuation, digits
    return _STATE_ALIAS.get(s, s)


def _need_index(d: dict | None) -> float | None:
    """Demand/burden composite in 0..1 (higher = more underserved population), from the
    NFHS indicators where 'more need' has a clear direction. Mean of available parts."""
    if not d:
        return None
    parts = []
    if d.get("institutional_birth") is not None:
        parts.append(1 - d["institutional_birth"] / 100)   # fewer in-facility births = more unmet
    if d.get("anc4") is not None:
        parts.append(1 - d["anc4"] / 100)                  # less antenatal care = more unmet
    if d.get("insurance") is not None:
        parts.append(1 - d["insurance"] / 100)             # less coverage = more financially exposed
    if d.get("stunting") is not None:
        parts.append(d["stunting"] / 100)                  # more child stunting = more burden
    if not parts:
        return None
    return sum(max(0.0, min(1.0, p)) for p in parts) / len(parts)


def _quantile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    i = q * (len(sorted_vals) - 1)
    lo = int(i); hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def _load_demand() -> dict:
    """state-join-key -> NFHS demand row. Empty if the overlay isn't loaded (graceful)."""
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT * FROM nfhs_state")
            return {_norm_state(r["state"]): r for r in cur.fetchall()}
    except Exception:  # noqa: BLE001 — table may not exist yet; map still works without demand
        return {}


def desert_grid(limit_states: int = 30) -> dict:
    """Trust-weighted supply aggregated by state × capability, separating confirmed
    care gaps (enough coverage, no trusted supply) from data-poor regions (unknown) —
    then overlays NFHS-5 demand so a gap in a high-burden state ranks as HIGH-RISK."""
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT state, count(*) n FROM facilities WHERE state IS NOT NULL AND state<>'' GROUP BY state")
        raw_totals = cur.fetchall()
        cur.execute(
            """SELECT f.state, t.capability,
                      count(*) AS n_scored,
                      count(*) FILTER (WHERE t.signal='strong') AS n_strong,
                      count(*) FILTER (WHERE t.signal IN ('strong','partial')) AS trusted
               FROM facilities f JOIN trust_signals t ON t.facility_id=f.id
               WHERE f.state IS NOT NULL AND f.state<>''
               GROUP BY f.state, t.capability""")
        raw_agg = cur.fetchall()

    demand = _load_demand()
    # Facility `state` is dirty (250+ spellings: "Tamilnadu" vs "Tamil Nadu", &/and variants,
    # even city names like "Mumbai"). Collapse to a canonical key; when NFHS demand is loaded
    # (the real 36 states/UTs) keep only keys that match one — dropping city-as-state junk.
    # Display label = the most common raw spelling for that key. Falls back to raw if no demand.
    restrict = bool(demand)
    totals: dict = {}
    name_votes: dict = {}
    for r in raw_totals:
        k = _norm_state(r["state"])
        if restrict and k not in demand:
            continue
        totals[k] = totals.get(k, 0) + r["n"]
        name_votes.setdefault(k, {})[r["state"].strip()] = r["n"]
    display = {k: max(v, key=v.get) for k, v in name_votes.items()}
    mapped = sum(totals.values())

    agg: dict = {}
    for r in raw_agg:
        k = _norm_state(r["state"])
        if restrict and k not in demand:
            continue
        cell = agg.setdefault(k, {}).setdefault(
            r["capability"], {"n_scored": 0, "n_strong": 0, "trusted": 0})
        cell["n_scored"] += r["n_scored"]
        cell["n_strong"] += r["n_strong"]
        cell["trusted"] += r["trusted"]

    states = sorted((k for k in totals if k in agg), key=lambda k: -totals[k])[:limit_states]

    # demand per displayed state + tercile thresholds for the high/med/low need tier
    need = {k: _need_index(demand.get(k)) for k in states}
    have = sorted(v for v in need.values() if v is not None)
    p33, p67 = _quantile(have, 1 / 3), _quantile(have, 2 / 3)

    def tier_of(ni: float | None) -> str:
        if ni is None or p67 is None:
            return "unknown"
        return "high" if ni >= p67 else ("med" if ni >= p33 else "low")

    def demand_block(k: str) -> dict | None:
        d = demand.get(k)
        if not d:
            return None
        ni = need[k]
        rnd = lambda x: round(x, 1) if x is not None else None  # noqa: E731
        return {"institutional_birth": rnd(d.get("institutional_birth")),
                "anc4": rnd(d.get("anc4")), "csection": rnd(d.get("csection")),
                "insurance": rnd(d.get("insurance")), "stunting": rnd(d.get("stunting")),
                "n_districts": d.get("n_districts"),
                "need_index": round(ni, 3) if ni is not None else None,
                "tier": tier_of(ni)}

    rows, gaps, risks = [], [], []
    for k in states:
        name = display[k]
        dem = demand_block(k)
        ni = need[k]
        cells = {}
        for cap in CAPS:
            a = agg.get(k, {}).get(cap)
            n_scored = a["n_scored"] if a else 0
            trusted = a["trusted"] if a else 0
            n_strong = a["n_strong"] if a else 0
            status = _gap_status(trusted, n_scored)
            rate = (trusted / n_scored) if n_scored else None
            # shortfall risk = health burden × thin trusted supply, where the rate is
            # meaningful (enough evaluated) and we have demand data. A *rate*, not a count,
            # so it's robust to how much of the state we've sampled.
            risk = round(ni * (1 - rate), 3) if (ni is not None and n_scored >= MIN_COVERAGE) else None
            high_risk = status == "gap" and tier_of(ni) == "high"
            cells[cap] = {"n_scored": n_scored, "trusted": trusted, "n_strong": n_strong,
                          "trusted_rate": round(rate, 2) if rate is not None else None,
                          "status": status, "risk": risk, "high_risk": high_risk}
            if status == "gap":
                gaps.append({"state": name, "capability": cap, "n_scored": n_scored,
                             "n_total": totals[k], "need_index": ni, "tier": tier_of(ni),
                             "high_risk": high_risk,
                             "institutional_birth": dem["institutional_birth"] if dem else None,
                             "insurance": dem["insurance"] if dem else None})
            if risk is not None:
                risks.append({"state": name, "capability": cap, "status": status,
                              "trusted": trusted, "n_scored": n_scored, "n_strong": n_strong,
                              "trusted_rate": round(rate, 2), "need_index": round(ni, 3),
                              "tier": tier_of(ni), "risk": risk,
                              "institutional_birth": dem["institutional_birth"] if dem else None,
                              "insurance": dem["insurance"] if dem else None,
                              "stunting": dem["stunting"] if dem else None})
        rows.append({"state": name, "n_total": totals[k], "cells": cells, "demand": dem})

    # rank: confirmed binary gaps first, then by demand pressure / coverage
    gaps.sort(key=lambda g: (not g["high_risk"], -(g["need_index"] or 0), -g["n_scored"]))
    # the headline: highest shortfall risk = burden × thin trusted supply
    risks.sort(key=lambda r: -r["risk"])
    return {"caps": CAPS, "states": rows, "top_gaps": gaps[:12], "top_risks": risks[:12],
            "min_coverage": MIN_COVERAGE, "demand_states": len(have),
            "n_states": len(states), "mapped_facilities": mapped}


def state_demand(state: str) -> dict | None:
    """NFHS-5 demand/burden for one state (normalized name match) + the need index.
    The Referral agent's demand tool — so a recommendation can weigh how underserved
    the surrounding population is, not just whether a facility exists."""
    d = _load_demand().get(_norm_state(state))
    if not d:
        return None
    ni = _need_index(d)
    rnd = lambda x: round(x, 1) if x is not None else None  # noqa: E731
    return {"state": state, "institutional_birth": rnd(d.get("institutional_birth")),
            "anc4": rnd(d.get("anc4")), "insurance": rnd(d.get("insurance")),
            "stunting": rnd(d.get("stunting")), "n_districts": d.get("n_districts"),
            "need_index": round(ni, 3) if ni is not None else None}


def readiness() -> dict:
    """Track 4 — data-readiness profile + a prioritized human-review queue:
    sparse fields, weak/suspicious claims, and over-claims (contradictions)."""
    fields = ["description", "capability", "procedure", "equipment",
              "number_doctors", "capacity", "year_established"]
    HOSPITAL_TYPES = ("hospital", "medicalcollege", "nursinghome", "medicalcenter")
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) n FROM facilities")
        total = cur.fetchone()["n"] or 1
        cur.execute("SELECT " + ", ".join(
            f"count(*) FILTER (WHERE {f} IS NOT NULL AND {f}<>'' AND {f}<>'null' AND {f}<>'[]') AS {f}"
            for f in fields) + " FROM facilities")
        row = cur.fetchone()
        coverage = [{"field": f, "pct": round(100 * row[f] / total), "n": row[f]} for f in fields]

        cur.execute("SELECT signal, count(*) n FROM trust_signals GROUP BY signal")
        dist = {"strong": 0, "partial": 0, "weak": 0, "none": 0}
        dist.update({r["signal"]: r["n"] for r in cur.fetchall()})

        cur.execute(
            f"""SELECT f.id, f.name, f.city, f.state, f.facility_type, t.capability, t.signal, t.confidence,
                  CASE WHEN t.signal='strong' AND lower(coalesce(f.facility_type,'')) NOT IN {HOSPITAL_TYPES}
                            AND t.capability IN ('icu','trauma','oncology','nicu') THEN 'over-claim'
                       WHEN t.signal='weak' THEN 'weak / generic claim'
                       ELSE 'low-confidence — verify' END AS flag
                FROM facilities f JOIN trust_signals t ON t.facility_id=f.id
                WHERE NOT EXISTS (SELECT 1 FROM reviews r WHERE r.facility_id=f.id AND r.action IN ('override','note'))
                  AND ( (t.signal='strong' AND lower(coalesce(f.facility_type,'')) NOT IN {HOSPITAL_TYPES}
                         AND t.capability IN ('icu','trauma','oncology','nicu'))
                     OR t.signal='weak'
                     OR (t.signal='partial' AND t.confidence < 0.4) )
                ORDER BY CASE WHEN t.signal='strong' THEN 0 WHEN t.signal='weak' THEN 1 ELSE 2 END, t.confidence
                LIMIT 40""")
        queue = cur.fetchall()
        cur.execute("SELECT count(DISTINCT facility_id) n FROM reviews WHERE action IN ('override','note')")
        reviewed = cur.fetchone()["n"]
    return {"total": total, "coverage": coverage, "signal_dist": dist, "queue": queue, "reviewed": reviewed}


SERVICE_CATS = ["medical", "surgical", "obgyn", "pediatrics", "dental", "diagnostic", "other"]
SERVICE_LABEL = {"medical": "Medical", "surgical": "Surgical", "obgyn": "OB/GYN", "pediatrics": "Pediatrics",
                 "dental": "Dental", "diagnostic": "Diagnostic", "other": "Other"}


def services_overview() -> dict:
    """Track 4 — clinical service-line classification + capacity (from facility_services):
    which of the 7 categories providers cover, bed capacity, and the completeness rules
    (an inpatient facility with no beds; a provider with no specialty)."""
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute("SELECT count(*) n FROM facility_services")
        except Exception:  # noqa: BLE001 — table not loaded yet
            return {"available": False}
        total = cur.fetchone()["n"]
        if not total:
            return {"available": False}
        parts = []
        for cat in SERVICE_CATS:
            parts.append(f"count(*) FILTER (WHERE (services->'{cat}'->>'offered')='true') AS off_{cat}")
            parts.append(f"count(*) FILTER (WHERE (services->'{cat}'->>'specialties')::int > 0) AS sp_{cat}")
            parts.append(f"coalesce(sum((services->'{cat}'->>'beds')::int),0) AS beds_{cat}")
        cur.execute("SELECT " + ", ".join(parts) + " FROM facility_services")
        r = cur.fetchone()
        categories = [{"key": cat, "label": SERVICE_LABEL[cat], "offered": r[f"off_{cat}"],
                       "with_specialists": r[f"sp_{cat}"], "beds": r[f"beds_{cat}"]} for cat in SERVICE_CATS]
        cur.execute(
            """SELECT coalesce(sum(total_beds),0) total_beds,
                      count(*) FILTER (WHERE total_beds>0) with_beds,
                      round(avg(n_categories)::numeric,1) avg_cats,
                      count(*) FILTER (WHERE facility_type IN ('hospital','medicalcollege','nursinghome','medicalcenter')) inpatient,
                      count(*) FILTER (WHERE missing_beds) missing_beds,
                      count(*) FILTER (WHERE missing_specialty) missing_specialty
               FROM facility_services""")
        a = cur.fetchone()
    return {"available": True, "total_facilities": total, "categories": categories,
            "total_beds": a["total_beds"], "with_beds": a["with_beds"],
            "avg_categories": float(a["avg_cats"] or 0), "inpatient": a["inpatient"],
            "missing_beds": a["missing_beds"], "missing_specialty": a["missing_specialty"]}


def district_rollup(limit: int = 16) -> dict:
    """Supply mapped to district via the PIN bridge: facilities, beds, physicians, and
    the bed-count completeness gap per district. The geography the referral 'local
    provider' and district-level planning both build on."""
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute("SELECT count(*) FILTER (WHERE district IS NOT NULL) m, "
                        "count(DISTINCT district) d FROM facility_services")
        except Exception:  # noqa: BLE001 — table/column not present yet
            return {"available": False}
        r = cur.fetchone()
        if not r["m"]:
            return {"available": False}
        # clean district→state from the PIN directory (the facility's own state field
        # is dirty); modal state per district.
        cur.execute(
            """WITH ds AS (
                 SELECT district, state FROM (
                   SELECT district, state,
                          row_number() OVER (PARTITION BY district ORDER BY count(*) DESC) rn
                   FROM pincode WHERE district IS NOT NULL GROUP BY district, state) z
                 WHERE rn=1)
               SELECT fs.district, ds.state, count(*) AS facilities,
                      count(*) FILTER (WHERE fs.total_beds>0) AS with_beds,
                      coalesce(sum(fs.total_beds),0) AS beds,
                      coalesce(sum(fs.n_doctors),0) AS physicians,
                      count(*) FILTER (WHERE fs.missing_beds) AS missing_beds
               FROM facility_services fs LEFT JOIN ds ON ds.district = fs.district
               WHERE fs.district IS NOT NULL
               GROUP BY fs.district, ds.state ORDER BY facilities DESC LIMIT %s""", (limit,))
        districts = cur.fetchall()
    return {"available": True, "mapped": r["m"], "n_districts": r["d"], "districts": districts}


def health() -> dict:
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT count(*) n FROM facilities")
            nf = cur.fetchone()["n"]
            cur.execute("SELECT count(*) n FROM trust_signals")
            nt = cur.fetchone()["n"]
        return {"ok": True, "facilities": nf, "trust_signals": nt}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
