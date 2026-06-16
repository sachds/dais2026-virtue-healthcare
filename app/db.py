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


# Chronic condition → the care team it needs (a diabetic needs eye + dental exams, etc.).
# Each role matches facilities whose `specialties` contain any of the keywords.
CARE_TEAMS: dict[str, list[tuple[str, list[str]]]] = {
    "diabetes": [
        ("Diabetes / endocrinology care", ["endocrin", "diabet"]),
        ("Dental exam (periodontal disease)", ["dentist", "dental", "odont"]),
        ("Eye exam (diabetic retinopathy)", ["ophthalmolog"]),
        ("Kidney check (nephrology)", ["nephrolog"]),
    ],
    "hypertension": [
        ("Cardiology / internal medicine", ["cardiolog", "internalmedicine"]),
        ("Eye exam", ["ophthalmolog"]),
        ("Kidney check (nephrology)", ["nephrolog"]),
    ],
    "pregnancy": [
        ("Obstetrics / maternity", ["obstetr", "gynec"]),
        ("Newborn / pediatrics", ["pediatr", "neonat"]),
    ],
}


def _location_centroid(location: str) -> tuple[float | None, float | None]:
    loc = (location or "").strip()
    if not loc:
        return (None, None)
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT avg(latitude) la, avg(longitude) lo FROM facilities "
                    "WHERE (city ILIKE %s OR state ILIKE %s) AND latitude IS NOT NULL",
                    (f"%{loc}%", f"%{loc}%"))
        r = cur.fetchone()
    if r and r["la"] is not None:
        return (float(r["la"]), float(r["lo"]))
    return (None, None)


def care_team(condition: str, location: str = "", per: int = 3) -> dict:
    """For a chronic condition, assemble the care team it needs — the NEAREST facilities
    (by lat/long from the patient's location) for each required specialty."""
    cond = (condition or "").strip().lower()
    spec = CARE_TEAMS.get(cond)
    if not spec:
        return {"available": False}
    clat, clon = _location_centroid(location)
    roles = []
    with _conn() as c, c.cursor() as cur:
        for label, keys in spec:
            where = " OR ".join(["f.specialties ILIKE %s"] * len(keys))
            ilike = [f"%{k}%" for k in keys]
            if clat is not None:
                cur.execute(
                    f"""SELECT f.id, f.name, f.city, f.state, f.facility_type,
                           ((f.latitude-%s)*(f.latitude-%s)+(f.longitude-%s)*(f.longitude-%s)) AS d2
                       FROM facilities f WHERE ({where}) AND f.latitude IS NOT NULL
                       ORDER BY d2 ASC LIMIT %s""",
                    [clat, clat, clon, clon] + ilike + [per])
            else:
                cur.execute(f"SELECT f.id, f.name, f.city, f.state, f.facility_type, NULL AS d2 "
                            f"FROM facilities f WHERE ({where}) LIMIT %s", ilike + [per])
            facs = cur.fetchall()
            for x in facs:
                x["km"] = round((x["d2"] ** 0.5) * 111, 1) if x.get("d2") is not None else None
                x.pop("d2", None)
            roles.append({"role": label, "facilities": facs})
    return {"available": True, "condition": cond, "location": location,
            "has_centroid": clat is not None, "roles": roles}


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


def disease_benchmarks(limit: int = 6) -> dict:
    """Establish prevalence benchmarks by geography: the national baseline for each
    condition and the worst districts above it, plus the anaemia × stunting combined
    child-nutrition burden (they go together). From nfhs_district."""
    conds = [("diabetes", "Diabetes — high blood sugar (women 15+)"),
             ("hypertension", "Hypertension — high BP (women 15+)"),
             ("anemia", "Child anaemia (6–59 months)"),
             ("stunting", "Child stunting (under 5)")]
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute("SELECT " + ", ".join(f"round(avg({k})::numeric,1)::float8 AS {k}" for k, _ in conds)
                        + " FROM nfhs_district")
            nat = cur.fetchone()
        except Exception:  # noqa: BLE001 — nfhs_district / anemia not loaded
            return {"available": False}
        conditions = []
        for k, label in conds:
            cur.execute(f"SELECT district, state, round({k}::numeric,1)::float8 AS v FROM nfhs_district "
                        f"WHERE {k} IS NOT NULL ORDER BY {k} DESC LIMIT %s", (limit,))
            conditions.append({"key": k, "label": label, "national": nat[k], "worst": cur.fetchall()})
        cur.execute(
            """SELECT district, state, round(anemia::numeric,1)::float8 AS anemia,
                      round(stunting::numeric,1)::float8 AS stunting
               FROM nfhs_district WHERE anemia IS NOT NULL AND stunting IS NOT NULL
               ORDER BY (anemia + stunting) DESC LIMIT %s""", (limit,))
        nutrition = cur.fetchall()
    return {"available": True, "conditions": conditions, "nutrition": nutrition}


def _dkey(district: str) -> str:
    return re.sub(r"\s+", " ", (district or "").strip()).upper()


def under_immunized(limit: int = 8, min_facilities: int = 3) -> list[dict]:
    """The lowest-immunization districts that ALSO have local supply to run a campaign —
    the agentic immunization campaign's targets (NFHS-5 × facility_services)."""
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute(
                """SELECT nd.district, nd.state,
                          round(nd.full_immunization::numeric,1)::float8 AS immunization,
                          round(nd.penta3::numeric,1)::float8 AS penta3,
                          round(nd.bcg::numeric,1)::float8 AS bcg,
                          round(nd.insurance::numeric,1)::float8 AS insurance,
                          count(fs.facility_id)::int AS facilities,
                          coalesce(sum(fs.n_doctors),0)::int AS physicians,
                          coalesce(sum(fs.total_beds),0)::int AS beds
                   FROM nfhs_district nd JOIN facility_services fs ON fs.district = nd.dkey
                   WHERE nd.full_immunization IS NOT NULL
                   GROUP BY nd.district, nd.state, nd.full_immunization, nd.penta3, nd.bcg, nd.insurance
                   HAVING count(fs.facility_id) >= %s
                   ORDER BY nd.full_immunization ASC LIMIT %s""", (min_facilities, limit))
            return cur.fetchall()
        except Exception:  # noqa: BLE001 — nfhs_district not loaded
            return []


def district_profile(district: str) -> dict:
    """NFHS-5 health indicators + our supply for one district — what the public-health
    agents reason over (campaign siting, isolation capacity)."""
    dk = _dkey(district)
    with _conn() as c, c.cursor() as cur:
        nfhs = None
        try:
            cur.execute("SELECT state, district, full_immunization, bcg, penta3, diabetes, "
                        "hypertension, institutional_birth, insurance, stunting, anemia "
                        "FROM nfhs_district WHERE dkey=%s LIMIT 1", (dk,))
            nfhs = cur.fetchone()
        except Exception:  # noqa: BLE001
            nfhs = None
        cur.execute(
            """SELECT count(*) AS facilities, coalesce(sum(total_beds),0) AS beds,
                      coalesce(sum(n_doctors),0) AS physicians,
                      count(*) FILTER (WHERE facility_type IN ('hospital','medicalcollege','nursinghome','medicalcenter')) AS hospitals
               FROM facility_services WHERE district=%s""", (dk,))
        supply = cur.fetchone()
        cur.execute(
            """SELECT f.name, f.city, fs.total_beds, fs.n_doctors
               FROM facility_services fs JOIN facilities f ON f.id=fs.facility_id
               WHERE fs.district=%s AND fs.total_beds>0
               ORDER BY fs.total_beds DESC NULLS LAST LIMIT 6""", (dk,))
        top = cur.fetchall()
    return {"district": district, "dkey": dk, "nfhs": nfhs, "supply": supply, "top_facilities": top}


def providers_in_region(district: str, limit: int = 12) -> list[dict]:
    """The providers in a district — who to target with an outbreak-response outreach,
    biggest-capacity first."""
    dk = _dkey(district)
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute(
                """SELECT fs.facility_id, f.name, fs.facility_type, fs.total_beds, fs.n_doctors, f.city
                   FROM facility_services fs JOIN facilities f ON f.id = fs.facility_id
                   WHERE fs.district = %s
                   ORDER BY coalesce(fs.total_beds,0) DESC, coalesce(fs.n_doctors,0) DESC LIMIT %s""",
                (dk, limit))
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def find_provider(name: str) -> dict | None:
    """Resolve a referring provider by name (best single match) — the facility the
    Copilot refers FROM, used to anchor location + nearest routing."""
    q = (name or "").strip()
    if not q:
        return None
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT id, name, city, state, latitude, longitude FROM facilities "
                    "WHERE name ILIKE %s ORDER BY (name ILIKE %s) DESC, length(name) ASC LIMIT 1",
                    (f"%{q}%", f"{q}%"))
        return cur.fetchone()


# --------------------------------------------------------------------------- #
# Procedure-specific referral ranking.
#
# A provider sending a patient for a SPECIFIC procedure (knee replacement, cataract,
# C-section…) wants the right *destination*, ranked by quality. This dataset has NO
# verified outcomes or procedure volume — so we rank facilities that LIST the procedure
# by a transparent capability + accreditation PROXY, and SURFACE (never score) the
# self-reported volume/success figures some facilities advertise. Honest by construction.
PROCEDURES: dict[str, dict] = {
    "knee replacement": {"label": "Knee replacement", "dept": "Orthopedics",
        "match": ["knee replacement", "knee arthroplasty", "total knee", "tkr"], "specialty": ["orthop"]},
    "hip replacement": {"label": "Hip replacement", "dept": "Orthopedics",
        "match": ["hip replacement", "hip arthroplasty", "total hip"], "specialty": ["orthop"]},
    "cataract surgery": {"label": "Cataract surgery", "dept": "Ophthalmology",
        "match": ["cataract", "phaco", "intraocular lens"], "specialty": ["ophthalmolog"]},
    "cesarean section": {"label": "Cesarean section (C-section)", "dept": "Obstetrics",
        "match": ["cesarean", "caesarean", "c-section", "c section", "lscs"], "specialty": ["obstetr", "gynec"]},
    "angioplasty": {"label": "Angioplasty / cardiac stent", "dept": "Cardiology",
        "match": ["angioplasty", "ptca", "coronary stent", "cardiac cath"], "specialty": ["cardiolog"]},
    "bypass surgery": {"label": "Coronary bypass (CABG)", "dept": "Cardiac surgery",
        "match": ["bypass surgery", "cabg", "coronary artery bypass"], "specialty": ["cardiacsurg", "cardiothoracic", "cardiovascular"]},
    "dialysis": {"label": "Dialysis", "dept": "Nephrology",
        "match": ["dialysis", "hemodialysis", "haemodialysis"], "specialty": ["nephrol"]},
    "hysterectomy": {"label": "Hysterectomy", "dept": "Gynecology",
        "match": ["hysterectomy"], "specialty": ["gynec", "obstetr"]},
    "hernia repair": {"label": "Hernia repair", "dept": "General surgery",
        "match": ["hernia"], "specialty": ["generalsurg", "laparoscop"]},
    "chemotherapy": {"label": "Chemotherapy", "dept": "Oncology",
        "match": ["chemotherapy"], "specialty": ["oncolog", "hemato"]},
}
_ADVANCED = [("robotic", "Robotic"), ("navigation", "Computer-navigated"), ("laparoscop", "Laparoscopic"),
             ("minimally invasive", "Minimally invasive"), ("arthroscop", "Arthroscopic")]
_ACCRED = [("nabh", "NABH"), ("jci", "JCI")]
# self-reported, unverifiable marketing figures — surfaced as a flag, NEVER scored.
_CLAIM_RE = [
    (re.compile(r"[\d,]{2,}\+?\s*(?:surgeries|procedures|operations|cases|transplants|patients)\b[\w\s,%]{0,26}", re.I), "volume"),
    (re.compile(r"\d{1,3}\s*%\s*(?:success|survival)[\w\s]{0,18}", re.I), "success rate"),
    (re.compile(r"(?:success|survival)\s*rate[\w\s:]{0,26}", re.I), "success rate"),
]


def detect_procedure(query: str) -> str | None:
    """Spot a specific procedure in the provider's free text (deterministic keyword match)."""
    ql = (query or "").lower()
    for key, spec in PROCEDURES.items():
        if any(kw in ql for kw in spec["match"]):
            return key
    return None


def _clamp_int(x) -> int:
    try:
        return max(0, min(100000, int(x)))
    except (TypeError, ValueError):
        return 0


def _proc_snippet(blob: str, matches: list[str], span: int = 78) -> str:
    low = blob.lower()
    for kw in matches:
        i = low.find(kw)
        if i >= 0:
            a, b = max(0, i - 14), min(len(blob), i + len(kw) + span)
            return ("…" if a else "") + " ".join(blob[a:b].split()) + ("…" if b < len(blob) else "")
    return ""


def procedure_ranking(procedure: str, location: str = "",
                      anchor: tuple | None = None, limit: int = 8) -> dict:
    """Rank facilities that LIST `procedure` by a capability + accreditation proxy
    (NABH/JCI · the matching specialty on record · advanced technique · scale).
    NOT verified outcomes — this dataset has none. Self-reported volume/success
    figures are surfaced as flags, never scored. Anchored to a referring provider's
    lat/long when given (nearest in range, then ranked by quality)."""
    spec = PROCEDURES.get(procedure)
    if spec:
        label, matches, spec_keys, dept = spec["label"], spec["match"], spec["specialty"], spec["dept"]
    else:
        label = (procedure or "").strip().title() or "Procedure"
        matches, spec_keys, dept = [m for m in [(procedure or "").strip().lower()] if m], [], None
    if not matches:
        return {"available": False, "procedure": label, "ranking": [], "n_matched": 0}

    blob_sql = ("lower(concat_ws(' ', coalesce(f.procedure,''), coalesce(f.capability,''), "
                "coalesce(f.description,''), coalesce(f.equipment,'')))")
    match_sql = " OR ".join([f"{blob_sql} LIKE %s"] * len(matches))
    args: list = [f"%{m}%" for m in matches]
    anchored = bool(anchor and anchor[0] is not None)
    loc_sql = ""
    if location.strip() and not anchored:
        loc_sql = " AND (f.city ILIKE %s OR f.state ILIKE %s)"
        args += [f"%{location.strip()}%"] * 2
    sql = (f"SELECT f.id, f.name, f.city, f.state, f.facility_type, f.latitude, f.longitude, "
           f"coalesce(f.specialties,'') AS specialties, "
           f"concat_ws(' ', coalesce(f.procedure,''), coalesce(f.capability,''), "
           f"coalesce(f.description,''), coalesce(f.equipment,'')) AS blob, "
           f"fs.total_beds, fs.n_doctors "
           f"FROM facilities f LEFT JOIN facility_services fs ON fs.facility_id = f.id "
           f"WHERE ({match_sql}){loc_sql} LIMIT 700")
    with _conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    n_matched = len(rows)

    if anchored:
        alat, alon = float(anchor[0]), float(anchor[1])
        keep = []
        for r in rows:
            if r["latitude"] is not None and r["longitude"] is not None:
                r["km"] = round(((float(r["latitude"]) - alat) ** 2 + (float(r["longitude"]) - alon) ** 2) ** 0.5 * 111, 1)
                keep.append(r)
        keep.sort(key=lambda r: r["km"])
        rows = keep[:30]   # nearest in range, then rank those by quality
    else:
        for r in rows:
            r["km"] = None

    ranked = []
    for r in rows:
        blob = r["blob"] or ""
        low = blob.lower()
        specs = (r["specialties"] or "").lower()
        score, badges = 0, []
        acc = next((lab for kw, lab in _ACCRED if kw in low or kw in specs), None)
        if acc:
            score += 3
            badges.append(acc + " accredited")
        has_spec = bool(spec_keys) and any(k in specs for k in spec_keys)
        if has_spec:
            score += 2
            badges.append((dept or "Specialty") + " on staff")
        adv = [lab for kw, lab in _ADVANCED if kw in low][:3]
        score += len(adv)
        badges += adv
        beds, docs = _clamp_int(r["total_beds"]), _clamp_int(r["n_doctors"])
        if beds >= 500:
            score += 2
        elif beds >= 150:
            score += 1
        if beds:
            badges.append(f"{beds} beds")
        if docs >= 30:
            score += 1
        claims = []
        for rx, kind in _CLAIM_RE:
            m = rx.search(blob)
            if m:
                claims.append({"text": " ".join(m.group(0).split())[:90], "kind": kind})
            if len(claims) >= 2:
                break
        caution = ""
        if spec_keys and not has_spec:
            caution = (f"lists {label.lower()} but no {dept.lower()} dept on record — "
                       "verify (may be a non-specific mention)")
        ranked.append({"id": r["id"], "name": r["name"], "city": r["city"], "state": r["state"],
                       "facility_type": r["facility_type"], "km": r["km"], "score": score, "beds": beds,
                       "badges": badges, "accredited": acc, "has_specialty": has_spec,
                       "caution": caution, "claims": claims, "evidence": _proc_snippet(blob, matches)})
    ranked.sort(key=lambda x: (-x["score"], x["km"] if x["km"] is not None else 1e9, -x["beds"]))
    return {"available": True, "procedure": label, "dept": dept, "n_matched": n_matched,
            "pool": len(rows), "anchored": anchored, "location": location.strip(),
            "ranking": ranked[:limit],
            "legend": ("NABH/JCI accreditation, the matching specialty on record, advanced technique "
                       "(robotic / navigation / laparoscopic) and scale (beds, doctors). Self-reported "
                       "volume/success figures are flagged, not scored. Real outcome ranking needs an "
                       "external procedure registry — connect one and this becomes verified, not a proxy."),
            "scored_on": ["NABH/JCI accreditation", "matching specialty on record",
                          "advanced technique", "beds & doctors"]}


def provider_card(facility_id: str) -> dict | None:
    """One provider's profile (name, type, capacity, service lines) for the outreach agent."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT f.name, f.city, f.state, fs.facility_type, fs.district, fs.total_beds,
                      fs.n_doctors, fs.services
               FROM facility_services fs JOIN facilities f ON f.id = fs.facility_id
               WHERE fs.facility_id = %s LIMIT 1""", (facility_id,))
        r = cur.fetchone()
    if not r:
        return None
    svc = r["services"] or {}
    offered = [SERVICE_LABEL[k] for k in SERVICE_CATS if (svc.get(k) or {}).get("offered")]
    return {"name": r["name"], "city": r["city"], "state": r["state"], "type": r["facility_type"],
            "district": r["district"], "beds": r["total_beds"], "doctors": r["n_doctors"], "services": offered}


def district_supply(capability: str = "any") -> dict:
    """District-level trusted supply with geographic centroids — for the desert MAP.
    Each district: centroid (avg facility lat/long), facility count, and whether it has
    trusted supply for the capability (served), is a gap (evaluated, none trusted), or
    is data-poor. capability is one of CAPS or 'any' (trusted supply for any capability)."""
    cap = capability if capability in CAPS else "any"
    join_filter = "" if cap == "any" else "AND t.capability = %s"
    args: list = [] if cap == "any" else [cap]
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute(f"""
              WITH ds AS (
                SELECT district, state FROM (
                  SELECT district, state,
                         row_number() OVER (PARTITION BY district ORDER BY count(*) DESC) rn
                  FROM pincode WHERE district IS NOT NULL GROUP BY district, state) z WHERE rn=1)
              SELECT fs.district, ds.state,
                     round(avg(f.latitude)::numeric, 4) lat, round(avg(f.longitude)::numeric, 4) lon,
                     count(DISTINCT f.id) n_fac,
                     count(DISTINCT t.facility_id) n_scored,
                     count(DISTINCT t.facility_id) FILTER (WHERE t.signal IN ('strong','partial')) trusted
              FROM facility_services fs
              JOIN facilities f ON f.id = fs.facility_id AND f.latitude IS NOT NULL AND f.longitude IS NOT NULL
              LEFT JOIN trust_signals t ON t.facility_id = fs.facility_id {join_filter}
              LEFT JOIN ds ON ds.district = fs.district
              WHERE fs.district IS NOT NULL
              GROUP BY fs.district, ds.state
              HAVING count(DISTINCT f.id) > 0""", args)
            rows = cur.fetchall()
        except Exception:  # noqa: BLE001 — pincode/facility_services not loaded
            return {"available": False, "capability": cap, "caps": CAPS, "districts": []}
    out = []
    for r in rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        trusted, n_scored = r["trusted"], r["n_scored"]
        status = "served" if trusted >= 1 else ("gap" if n_scored >= 3 else "datapoor")
        out.append({"district": r["district"], "state": r["state"],
                    "lat": float(r["lat"]), "lon": float(r["lon"]), "n_fac": r["n_fac"],
                    "n_scored": n_scored, "trusted": trusted, "status": status})
    return {"available": True, "capability": cap, "caps": CAPS, "districts": out}


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


def referral_network(capability: str, state: str, max_referrers: int = 400) -> dict:
    """Infer the referral graph for one capability in one state by coordinating the
    Copilot's nearest-trusted resolution across EVERY facility: split facilities into
    trusted-C destinations vs referrers (no trusted supply for C), edge each referrer
    to its nearest destination, aggregate destination load (in-degree), and surface the
    chokepoints the whole region depends on — flagging single-points-of-failure (sole
    destination, or heavy load on a node whose own C evidence is only partial)."""
    cap = capability if capability in CAPS else "icu"
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT f.id, f.name, f.city, f.facility_type, f.latitude, f.longitude,
                      max(CASE WHEN t.capability=%s AND t.signal IN ('strong','partial') THEN 1 ELSE 0 END) AS trusted,
                      max(CASE WHEN t.capability=%s AND t.signal='strong' THEN 2
                               WHEN t.capability=%s AND t.signal='partial' THEN 1 ELSE 0 END) AS sigrank
               FROM facilities f LEFT JOIN trust_signals t ON t.facility_id=f.id
               WHERE f.state=%s AND f.latitude IS NOT NULL AND f.longitude IS NOT NULL
               GROUP BY f.id, f.name, f.city, f.facility_type, f.latitude, f.longitude""",
            (cap, cap, cap, state))
        rows = cur.fetchall()

    dests = [r for r in rows if r["trusted"] == 1]
    referrers_all = [r for r in rows if r["trusted"] == 0]
    n_referrer_total = len(referrers_all)
    referrers = referrers_all[:max_referrers]
    base = {"available": True, "capability": cap, "state": state, "caps": CAPS,
            "n_dest": len(dests), "n_referrer": n_referrer_total,
            "n_referrer_plotted": len(referrers)}

    if not dests:
        return {**base, "no_destination": True, "nodes": [], "edges": [], "bottlenecks": [], "max_share": 0}

    for d in dests:
        d["in_degree"] = 0
        d["km_sum"] = 0.0
    edges = []
    for r in referrers:
        rlat, rlon = float(r["latitude"]), float(r["longitude"])
        best, best_d2 = None, None
        for d in dests:
            d2 = (float(d["latitude"]) - rlat) ** 2 + (float(d["longitude"]) - rlon) ** 2
            if best_d2 is None or d2 < best_d2:
                best_d2, best = d2, d
        best["in_degree"] += 1
        best["km_sum"] += best_d2 ** 0.5 * 111
        edges.append({"flat": round(rlat, 4), "flon": round(rlon, 4),
                      "tlat": round(float(best["latitude"]), 4), "tlon": round(float(best["longitude"]), 4)})

    total = len(referrers) or 1
    nodes = []
    sole = len(dests) == 1
    for d in dests:
        deg = d["in_degree"]
        nodes.append({"id": d["id"], "name": d["name"], "city": d["city"], "facility_type": d["facility_type"],
                      "lat": round(float(d["latitude"]), 4), "lon": round(float(d["longitude"]), 4),
                      "in_degree": deg, "share": round(100 * deg / total),
                      "trust": "strong" if d["sigrank"] == 2 else "partial",
                      "avg_km": round(d["km_sum"] / deg, 1) if deg else None})
    nodes.sort(key=lambda n: -n["in_degree"])
    # Flag the risks once ranks are known. The systemic risk is rarely raw share — it's a
    # MOST-DEPENDED-ON node whose own evidence is only partial (everyone routes to a place
    # that may not actually deliver), the sole destination, or a true high-load funnel.
    cu = cap.upper()
    for rank, n in enumerate(nodes):
        risk, why = "", ""
        if sole and n["in_degree"]:
            risk, why = "sole", f"the ONLY trusted {cu} facility in {state} — referrals have no fallback"
        elif n["share"] >= 40:
            risk, why = "load", f"{n['share']}% of {state}'s {cu} referrals funnel to this one node"
        elif rank < 3 and n["in_degree"] >= 3 and n["trust"] == "partial":
            risk, why = "weak-hub", (f"the #{rank + 1} most-depended-on {cu} destination "
                                     f"({n['in_degree']} facilities), but its OWN {cu} evidence is only partial")
        n["risk"], n["why"], n["spof"] = risk, why, bool(risk)
    bottlenecks = [n for n in nodes if n["in_degree"] > 0][:8]
    return {**base, "no_destination": False, "nodes": nodes, "edges": edges,
            "bottlenecks": bottlenecks, "sole": sole,
            "max_share": nodes[0]["share"] if nodes else 0,
            "n_spof": sum(1 for n in nodes if n["spof"])}


def network_states(capability: str, limit: int = 14) -> list[dict]:
    """States with a meaningful referral funnel for C (enough referrers, few enough
    trusted destinations) — the picklist for the Care-Network view, worst funnel first."""
    cap = capability if capability in CAPS else "icu"
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """WITH g AS (
                 SELECT f.state, f.id,
                        max(CASE WHEN t.capability=%s AND t.signal IN ('strong','partial') THEN 1 ELSE 0 END) trusted
                 FROM facilities f LEFT JOIN trust_signals t ON t.facility_id=f.id
                 WHERE f.latitude IS NOT NULL AND f.state IS NOT NULL AND f.state<>''
                 GROUP BY f.state, f.id)
               SELECT state, count(*) n_geo, sum(trusted) n_dest, sum(1-trusted) n_referrer
               FROM g GROUP BY state
               HAVING sum(trusted) >= 1 AND sum(1-trusted) >= 20
               ORDER BY (sum(1-trusted)::float / greatest(sum(trusted),1)) DESC LIMIT %s""",
            (cap, limit))
        return [{"state": r["state"], "n_dest": int(r["n_dest"]), "n_referrer": int(r["n_referrer"]),
                 "ratio": round(r["n_referrer"] / max(1, r["n_dest"]))} for r in cur.fetchall()]


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
