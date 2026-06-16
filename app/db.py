"""Data layer for the Facility Trust Desk. Reads facilities + precomputed trust
signals from Lakebase, and persists analyst reviews (overrides/notes/shortlists)."""
from __future__ import annotations

import json
import os
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
    caps = []
    for cap in CAPS:
        s = signals.get(cap, {"capability": cap, "signal": "none", "confidence": 0,
                              "evidence": [], "rationale": "", "model": None})
        s["override"] = overrides.get(cap)
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


def desert_grid(limit_states: int = 30) -> dict:
    """Trust-weighted supply aggregated by state × capability, separating confirmed
    care gaps (enough coverage, no trusted supply) from data-poor regions (unknown)."""
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT state, count(*) n FROM facilities WHERE state IS NOT NULL AND state<>'' GROUP BY state")
        totals = {r["state"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            """SELECT f.state, t.capability,
                      count(*) AS n_scored,
                      count(*) FILTER (WHERE t.signal='strong') AS n_strong,
                      count(*) FILTER (WHERE t.signal IN ('strong','partial')) AS trusted
               FROM facilities f JOIN trust_signals t ON t.facility_id=f.id
               WHERE f.state IS NOT NULL AND f.state<>''
               GROUP BY f.state, t.capability""")
        agg: dict = {}
        for r in cur.fetchall():
            agg.setdefault(r["state"], {})[r["capability"]] = r

    states = sorted((s for s in totals if s in agg), key=lambda s: -totals[s])[:limit_states]
    rows, gaps = [], []
    for s in states:
        cells = {}
        for cap in CAPS:
            a = agg.get(s, {}).get(cap)
            n_scored = a["n_scored"] if a else 0
            trusted = a["trusted"] if a else 0
            status = _gap_status(trusted, n_scored)
            cells[cap] = {"n_scored": n_scored, "trusted": trusted,
                          "n_strong": a["n_strong"] if a else 0, "status": status}
            if status == "gap":
                gaps.append({"state": s, "capability": cap, "n_scored": n_scored, "n_total": totals[s]})
        rows.append({"state": s, "n_total": totals[s], "cells": cells})
    gaps.sort(key=lambda g: (-g["n_scored"], -g["n_total"]))
    return {"caps": CAPS, "states": rows, "top_gaps": gaps[:12], "min_coverage": MIN_COVERAGE}


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
