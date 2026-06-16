"""Referral Copilot — a small agent: PLAN (parse the need + location) → ACT
(retrieve candidates from Lakebase) → REASON (rank, cite evidence, flag uncertainty).
Runs live on the Databricks-served LLM."""
from __future__ import annotations

import json

from app import db, llm

CAPS = db.CAPS


def plan(query: str) -> dict:
    sys = ("You convert a healthcare planner's free-text request into structured search parameters. "
           "Capabilities are ONLY: icu, maternity, emergency, oncology, trauma, nicu. Map synonyms "
           "(cancer->oncology, delivery/childbirth->maternity, newborn/neonatal->nicu, accident/injury->trauma, "
           "critical/intensive care->icu, casualty->emergency). Extract the location as written.")
    usr = (f'Request: "{query}"\nReturn STRICT JSON: '
           '{"capabilities": ["..."], "location": "..."} (capabilities from the allowed list only; location "" if none).')
    try:
        p = llm.chat_json([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 300)
    except Exception:
        p = {}
    caps = [c for c in (p.get("capabilities") or []) if c in CAPS]
    return {"capabilities": caps, "location": (p.get("location") or "").strip()}


def _trim(cand: dict) -> dict:
    sigs = cand.get("sigs") or {}
    compact = {}
    for cap, s in sigs.items():
        ev = s.get("evidence") or []
        compact[cap] = {"signal": s["signal"], "confidence": s.get("confidence"),
                        "evidence": (ev[0].get("snippet") if ev else None)}
    return {"id": cand["id"], "name": cand["name"], "city": cand.get("city"),
            "state": cand.get("state"), "signals": compact}


def reason(query: str, p: dict, candidates: list[dict]) -> dict:
    need = ", ".join(p["capabilities"]) or "that need"
    where = f" near {p['location']}" if p["location"] else ""
    if not candidates:
        return {"answer": f"No facilities with supporting evidence for {need}{where}. "
                          "Try a wider area or a different capability.", "shortlist": []}
    trimmed = [_trim(c) for c in candidates]
    sys = ("You are a referral copilot for a healthcare planner. Recommend where to send a patient using ONLY the "
           "provided candidates and their trust signals. Be honest about uncertainty: prefer 'strong' evidence, flag "
           "'partial'/'weak' as needing confirmation, never invent capabilities, and always cite the evidence snippet.")
    usr = (f'Request: "{query}"\nNeed: {p["capabilities"]}{where}\n'
           f'Candidates with trust signals + a cited snippet:\n{json.dumps(trimmed, ensure_ascii=False)}\n\n'
           'Return STRICT JSON: {"answer": "2-3 sentence recommendation that cites evidence and flags uncertainty", '
           '"shortlist": [{"id": "...", "name": "...", "why": "one line citing the signal + evidence", '
           '"caution": "uncertainty note, or empty"}]}. Rank strongest evidence first; include 3-5.')
    try:
        out = llm.chat_json([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 700)
        ids = {c["id"] for c in trimmed}
        out["shortlist"] = [s for s in out.get("shortlist", []) if s.get("id") in ids][:5]
        return out
    except Exception:
        return {"answer": "Ranked by strongest evidence (live synthesis unavailable).",
                "shortlist": [{"id": c["id"], "name": c["name"], "why": "", "caution": ""} for c in trimmed[:5]]}


def run(query: str) -> dict:
    p = plan(query)
    candidates = db.copilot_candidates(p["capabilities"], p["location"], limit=6)
    rec = reason(query, p, candidates)
    return {"plan": p, "n_candidates": len(candidates),
            "answer": rec.get("answer"), "shortlist": rec.get("shortlist", [])}
