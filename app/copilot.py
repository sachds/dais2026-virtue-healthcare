"""Referral Copilot — a governed, multi-agent referral mesh.

Not one model call: a small team of roles over the shared trust substrate
(app/agent_tools.py), gated by a code-level governance policy (app/policy.py) —
the same shape an Omnigent agent runs (mcp_server.py mounts the same tools, and
agents/referral runs the same loop under the real harness).

  PLAN       parse the need + location
  RETRIEVE   find_facilities — evidence-backed candidates from Lakebase
  SCRUTINIZE facility_evidence — pull each candidate's full cited record
  SKEPTIC    adversarially challenge each claim from its own evidence
  GOVERN     policy.gate — block uncredible / refuted, flag over-claims
  COMPOSE    write the answer + shortlist over what SURVIVED, citing evidence

Every step is recorded in a `trace` (with provenance), so the planner sees the
agent's work — including what it was *not allowed* to recommend, and why.
"""
from __future__ import annotations

import json

from app import agent_tools, db, llm, policy

CAPS = db.CAPS
MODEL = llm.ENDPOINT  # provenance shown in the trace


# --------------------------------------------------------------------------- #
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


def scrutinize(candidates: list[dict]) -> None:
    """Pull each candidate's FULL cited record (all capabilities) and attach the
    all-caps strong count, so governance can catch blanket over-claims. In-place."""
    for c in candidates:
        ev = agent_tools.facility_evidence(c["id"])
        caps = ev.get("capabilities") or []
        c["n_strong_all"] = sum(1 for x in caps if x.get("signal") == "strong")


def skeptic(query: str, caps: list[str], candidates: list[dict]) -> dict:
    """Adversarial reviewer: for each candidate's requested capability, decide if the
    CITED EVIDENCE truly supports a real, usable capability. Returns {id: {cap: {verdict, why}}}.
    verdict ∈ uphold | doubt | refute. One batched call; deterministic empty on failure."""
    items = []
    for c in candidates:
        sigs = c.get("signals") or {}
        ev = {cap: sigs[cap].get("snippet") for cap in caps if sigs.get(cap) and sigs[cap].get("snippet")}
        if ev:
            items.append({"id": c["id"], "name": c.get("name"), "facility_type": c.get("facility_type"), "evidence": ev})
    if not items:
        return {}
    sys = ("You are a SKEPTICAL medical reviewer. Your job is to find reasons a cited claim does NOT establish a "
           "real, usable clinical capability — generic/marketing language ('all specialties', 'world-class'), a "
           "service mismatched to the capability (a screening camp is not oncology treatment; a first-aid room is "
           "not an ICU), or a claim implausible for the facility type. Judge ONLY from the cited text.")
    usr = (f'Request: "{query}". For each facility+capability, return a verdict on whether the cited evidence '
           f'supports a REAL capability.\n{json.dumps(items, ensure_ascii=False)}\n\n'
           'Return STRICT JSON {"verdicts":[{"id":"...","capability":"...","verdict":"uphold|doubt|refute",'
           '"why":"reason under 12 words"}]}. Default to "uphold" when the evidence is specific and on-point.')
    try:
        out = llm.chat_json([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 1500)
    except Exception:
        return {}
    by_id: dict = {}
    for v in out.get("verdicts", []):
        if v.get("verdict") in ("uphold", "doubt", "refute"):
            by_id.setdefault(v.get("id"), {})[v.get("capability")] = {"verdict": v["verdict"], "why": v.get("why", "")}
    return by_id


def compose(query: str, caps: list[str], passed: list[dict]) -> dict:
    """Write the recommendation + per-item why/caution over the SURVIVING candidates.
    The shortlist itself is governed by code (only `passed` reaches here); the model
    only writes prose. Deterministic fallback if the model is unavailable."""
    if not passed:
        return {"answer": "", "why": {}}
    brief = [{"id": c["id"], "name": c["name"], "capability": c["cap"], "signal": c["signal"],
              "evidence": c.get("snippet"), "verdict": c["verdict"],
              "caution": "; ".join(c.get("reasons") or [])} for c in passed]
    sys = ("You are a referral copilot for a healthcare planner. Recommend where to send the patient using ONLY the "
           "provided (already vetted) candidates. Cite the evidence. For any candidate marked verdict='flag', you MUST "
           "carry its caution. Never overstate — these are claims to verify, not certified facts.")
    usr = (f'Request: "{query}" · need {caps}\nVetted candidates:\n{json.dumps(brief, ensure_ascii=False)}\n\n'
           'Return STRICT JSON {"answer":"2-3 sentence recommendation citing evidence and flagging uncertainty",'
           '"items":[{"id":"...","why":"one line citing the signal + evidence","caution":"the mandatory caution, or empty"}]}.')
    try:
        out = llm.chat_json([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 800)
        why = {i.get("id"): {"why": i.get("why", ""), "caution": i.get("caution", "")} for i in out.get("items", [])}
        return {"answer": out.get("answer", ""), "why": why}
    except Exception:
        return {"answer": "Ranked by strongest surviving evidence (live synthesis unavailable).", "why": {}}


def run(query: str) -> dict:
    trace: list[dict] = []

    p = plan(query)
    caps = p["capabilities"] or CAPS
    where = f" near {p['location']}" if p["location"] else ""
    trace.append({"step": "plan", "role": "Planner", "model": MODEL,
                  "detail": f"parsed need: {', '.join(p['capabilities']) or 'any capability'}{where}"})

    candidates = agent_tools.find_facilities(caps, p["location"], limit=6)
    trace.append({"step": "retrieve", "role": "Retriever", "tool": "find_facilities",
                  "detail": f"{len(candidates)} candidates with supporting evidence in Lakebase"})

    if not candidates:
        return {"plan": p, "trace": trace, "n_candidates": 0, "blocked": [],
                "answer": f"No facilities with supporting evidence for {', '.join(p['capabilities']) or 'that need'}{where}. "
                          "Try a wider area or a different capability.", "shortlist": []}

    scrutinize(candidates)
    trace.append({"step": "scrutinize", "role": "Investigator", "tool": "facility_evidence",
                  "detail": f"pulled full cited records for {len(candidates)} candidates"})

    verdicts = skeptic(query, caps, candidates)
    flat = [v for caps_v in verdicts.values() for v in caps_v.values()]
    n_ref = sum(1 for v in flat if v["verdict"] == "refute")
    n_doubt = sum(1 for v in flat if v["verdict"] == "doubt")
    trace.append({"step": "skeptic", "role": "Skeptic", "model": MODEL,
                  "detail": f"challenged {len(flat)} claims — {n_ref} refuted, {n_doubt} doubted"})

    passed, blocked = policy.gate(candidates, caps, verdicts)
    # order: allow before flag; strong before partial
    passed.sort(key=lambda r: (r["verdict"] != "allow", r["signal"] != "strong"))
    n_flag = sum(1 for r in passed if r["verdict"] == "flag")
    trace.append({"step": "govern", "role": "Policy", "tool": "policy.gate",
                  "detail": f"{len(passed)} pass ({n_flag} flagged), {len(blocked)} blocked"})

    demand = agent_tools.state_demand(p["location"]) if p["location"] else None
    if demand and demand.get("need_index") is not None:
        trace.append({"step": "demand", "role": "Demand analyst", "tool": "state_demand",
                      "detail": f"{demand['state']}: NFHS need {demand['need_index']} "
                                f"({demand.get('institutional_birth')}% births in-facility, {demand.get('insurance')}% insured)"})

    comp = compose(query, caps, passed)
    trace.append({"step": "compose", "role": "Composer", "model": MODEL,
                  "detail": f"ranked {len(passed)} evidence-backed referrals"})

    shortlist = []
    for c in passed[:5]:
        w = comp["why"].get(c["id"], {})
        default_why = (f"{c['cap']}: {c['signal']} evidence — \"{c['snippet']}\""
                       if c.get("snippet") else f"{c['cap']}: {c['signal']} evidence")
        shortlist.append({"id": c["id"], "name": c["name"], "city": c.get("city"), "state": c.get("state"),
                          "cap": c["cap"], "signal": c["signal"], "verdict": c["verdict"],
                          "why": w.get("why") or default_why,
                          "caution": w.get("caution") or "; ".join(c.get("reasons") or [])})

    return {"plan": p, "trace": trace, "n_candidates": len(candidates),
            "answer": comp["answer"] or "Ranked by strongest surviving evidence.",
            "shortlist": shortlist, "blocked": blocked, "demand": demand}
