"""Trust substrate as agent tools.

The Facility Trust Desk's Lakebase, exposed as a small set of named tools an
agent can call to plan → retrieve → reason over evidence-cited trust signals.
ONE source of truth for both transports:
  • the in-process Referral Copilot (app/copilot.py) imports and calls these;
  • the Omnigent harness mounts the same functions over MCP (mcp_server.py).

Each tool returns plain JSON-able data with the *cited evidence* attached, so
whatever calls it can show its work and never has to trust an unsourced claim.
"""
from __future__ import annotations

from app import db

CAPS = db.CAPS


def _compact(cand: dict) -> dict:
    sigs = cand.get("sigs") or {}
    out = {}
    for cap, s in sigs.items():
        ev = s.get("evidence") or []
        out[cap] = {"signal": s["signal"], "confidence": s.get("confidence"),
                    "snippet": ev[0].get("snippet") if ev else None}
    return {"id": cand["id"], "name": cand["name"], "city": cand.get("city"),
            "state": cand.get("state"), "facility_type": cand.get("facility_type"),
            "signals": out}


def find_facilities(capabilities: list[str], location: str = "", limit: int = 6) -> list[dict]:
    """Retrieve facilities that have *supporting evidence* for the requested
    capabilities in a location, ranked by trust signal. Capabilities must be from
    icu|maternity|emergency|oncology|trauma|nicu. Returns compact candidates, each
    with per-capability {signal, confidence, cited snippet}."""
    caps = [c for c in (capabilities or []) if c in CAPS]
    rows = db.copilot_candidates(caps, (location or "").strip(), limit=limit)
    return [_compact(r) for r in rows]


def facility_evidence(facility_id: str) -> dict:
    """Full per-capability trust signals + the exact cited evidence for one
    facility (applies any analyst override). Use to scrutinize a candidate."""
    d = db.get_facility(facility_id)
    if not d:
        return {"error": "facility not found", "id": facility_id}
    f = d["facility"]
    caps = [{"capability": c["capability"], "signal": c.get("override") or c["signal"],
             "confidence": c.get("confidence"),
             "evidence": [e.get("snippet") for e in (c.get("evidence") or []) if e.get("snippet")]}
            for c in d["capabilities"]]
    return {"id": f["id"], "name": f.get("name"), "city": f.get("city"),
            "state": f.get("state"), "facility_type": f.get("facility_type"),
            "capabilities": caps}


def state_demand(state: str) -> dict:
    """NFHS-5 health-burden context for a state (need index + indicators), so a
    recommendation can weigh how underserved the surrounding population is."""
    return db.state_demand(state) or {"state": state, "need_index": None,
                                       "note": "no NFHS-5 demand match for this state"}


def record_decision(facility_id: str, body: str, capability: str | None = None,
                    user_id: str = "referral-agent") -> dict:
    """Persist a referral decision/note to Lakebase (append-only `reviews`), so the
    agent's recommendation is captured as a durable, attributable action."""
    row = db.record_review("decision", facility_id=facility_id, capability=capability,
                           body=body, user_id=user_id)
    return {"ok": True, "id": row["id"], "facility_id": facility_id}


def under_immunized_districts(limit: int = 8) -> list[dict]:
    """The lowest childhood-immunization districts that have local supply to run a
    campaign (NFHS-5 × facilities) — the immunization agent's targets."""
    return db.under_immunized(limit=limit)


def district_profile(district: str) -> dict:
    """NFHS-5 health indicators (immunization, NCD, maternal) + our supply (facilities,
    beds, physicians, top hospitals) for one district — for campaign siting / outbreak capacity."""
    return db.district_profile(district)


def referral_network(capability: str, state: str) -> dict:
    """Coordinate the nearest-trusted resolution across EVERY facility in a state and
    aggregate it into the inferred referral graph: which few destinations the whole
    region routes its `capability` referrals to, and the single-points-of-failure that
    carry heavy load on only-partial evidence. The system-level view a single referral
    can't see — the same tool the in-app Care Network and an Omnigent fleet both call."""
    return db.referral_network(capability, state)


def siting_impact(capability: str, state: str) -> dict:
    """Mission-siting counterfactual over the referral network: rank existing facilities
    by the impact of resourcing them to become a trusted `capability` destination —
    referrers given a closer option, travel saved, and load pulled off the chokepoint.
    Where to place the next specialist; the same tool the Care Network UI and a fleet call."""
    return db.siting_impact(capability, state)


# Tool registry — names → callables, used by mcp_server.py and the copilot trace.
TOOLS = {
    "find_facilities": find_facilities,
    "facility_evidence": facility_evidence,
    "state_demand": state_demand,
    "record_decision": record_decision,
    "under_immunized_districts": under_immunized_districts,
    "district_profile": district_profile,
    "referral_network": referral_network,
    "siting_impact": siting_impact,
}
