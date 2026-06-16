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
import re

from app import agent_tools, db, llm, policy

CAPS = db.CAPS
MODEL = llm.ENDPOINT  # provenance shown in the trace


# --------------------------------------------------------------------------- #
def plan(query: str) -> dict:
    sys = ("You convert a healthcare planner's free-text request into structured search parameters. "
           "Capabilities are ONLY: icu, maternity, emergency, oncology, trauma, nicu. Map synonyms "
           "(cancer->oncology, delivery/childbirth->maternity, newborn/neonatal->nicu, accident/injury->trauma, "
           "critical/intensive care->icu, casualty->emergency). Also detect a chronic CONDITION the patient HAS "
           "(diabetes, hypertension, pregnancy) and the number of visits this month if stated. Extract the location.")
    usr = (f'Request: "{query}"\nReturn STRICT JSON: {{"capabilities": ["..."], "location": "...", '
           '"condition": "diabetes|hypertension|pregnancy|none", "visits": 0}} (capabilities from the allowed list; '
           'condition ONLY if the patient has one, else "none"; visits = integer visits this month if mentioned, else 0).')
    try:
        p = llm.chat_json([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 300)
    except Exception:
        p = {}
    caps = [c for c in (p.get("capabilities") or []) if c in CAPS]
    cond = (p.get("condition") or "none").strip().lower()
    if cond not in db.CARE_TEAMS:
        cond = "none"
    try:
        visits = int(p.get("visits") or 0)
    except (TypeError, ValueError):
        visits = 0
    # deterministic safety net — the LLM is inconsistent about condition / visit count
    ql = query.lower()
    if cond == "none":
        for kw, cc in (("diabet", "diabetes"), ("hypertens", "hypertension"), ("blood pressure", "hypertension"),
                       ("pregnan", "pregnancy"), ("antenatal", "pregnancy"), ("expecting", "pregnancy")):
            if kw in ql and cc in db.CARE_TEAMS:
                cond = cc
                break
    if not visits:
        m = re.search(r"(\d+)\s*(?:visit|time)", ql)
        if m:
            visits = int(m.group(1))
    return {"capabilities": caps, "location": (p.get("location") or "").strip(),
            "condition": cond, "visits": visits, "procedure": db.detect_procedure(query)}


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


def _compose_care_team(query: str, cond: str, location: str, ct: dict, escalation: str | None) -> str:
    roles = [{"role": r["role"], "nearest": (r["facilities"][0]["name"] if r["facilities"] else None),
              "km": (r["facilities"][0].get("km") if r["facilities"] else None)} for r in ct.get("roles", [])]
    sys = ("You are a referral copilot assembling a CARE TEAM for a patient with a chronic condition. In 2-3 sentences "
           "explain why this condition needs this multi-specialty team (e.g. a diabetic needs an annual eye exam for "
           "retinopathy and dental care for periodontal disease), naming the nearest provider for each. If an escalation "
           "note is given, state it plainly. Use ONLY the providers given; invent none.")
    usr = (f'Request: "{query}" · condition: {cond} · near {location or "—"}\nCare team (nearest providers):\n'
           f'{json.dumps(roles, ensure_ascii=False)}\n' + (f"Escalation: {escalation}\n" if escalation else "")
           + "Return a short plain-text recommendation (no JSON, no markdown).")
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 500)
    except Exception:
        parts = [f"{r['role']} → {r['nearest']}" for r in roles if r["nearest"]]
        return (f"Care team for {cond}{' near ' + location if location else ''}: " + "; ".join(parts)
                + (". " + escalation if escalation else "."))


def care_team_referral(query: str, p: dict) -> dict:
    cond, loc, visits = p["condition"], p["location"], p.get("visits", 0)
    trace = [{"step": "plan", "role": "Planner", "model": MODEL,
              "detail": f"chronic condition: {cond}" + (f" · near {loc}" if loc else "")
                        + (f" · {visits} visits this month" if visits else "")}]
    ct = db.care_team(cond, loc)
    roles = ct.get("roles", [])
    trace.append({"step": "team", "role": "Care-team", "tool": "care_team",
                  "detail": f"assembled a {cond} care team across {len(roles)} specialties"
                            + (" — nearest by distance" if ct.get("has_centroid") else "")})
    escalation = None
    if visits and visits >= 2:
        escalation = (f"{visits} visits this month — escalate from primary care to a specialist and a hospital "
                      "(don't keep managing this in an outpatient clinic).")
        trace.append({"step": "escalate", "role": "Escalation", "tool": "rule",
                      "detail": f"{visits} visits this month ≥ 2 → escalate to specialist + hospital"})
    answer = _compose_care_team(query, cond, loc, ct, escalation)
    trace.append({"step": "compose", "role": "Composer", "model": MODEL, "detail": "drafted the care-team referral"})
    return {"mode": "care_team", "plan": p, "trace": trace, "care_team": roles,
            "escalation": escalation, "answer": answer}


def _capability_referral(query: str, p: dict) -> dict:
    trace: list[dict] = []
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

    return {"mode": "referral", "plan": p, "trace": trace, "n_candidates": len(candidates),
            "answer": comp["answer"] or "Ranked by strongest surviving evidence.",
            "shortlist": shortlist, "blocked": blocked, "demand": demand}


def _compose_procedure(query: str, label: str, location: str, ranking: list[dict]) -> str:
    """Write the 2-3 sentence pick over the ranked destinations — honest that this is a
    capability + accreditation PROXY, not verified outcomes."""
    if not ranking:
        return ""
    brief = [{"name": x["name"], "city": x.get("city"), "km": x.get("km"), "score": x["score"],
              "badges": x.get("badges"), "accredited": x.get("accredited"), "caution": x.get("caution"),
              "self_reported_claims": [c["kind"] for c in (x.get("claims") or [])]} for x in ranking[:3]]
    sys = ("You are a referral copilot helping a PROVIDER pick where to send a patient for a specific PROCEDURE. "
           "You are given facilities that LIST the procedure, ranked by a transparent capability + accreditation "
           "PROXY (NABH/JCI accreditation, the matching specialty on record, advanced technique, scale). You do NOT "
           "have verified clinical outcomes or real procedure volume. In 2-3 sentences: name the top choice and why "
           "(cite its accreditation / specialty / technique / distance), then state plainly that this ranks capability "
           "and accreditation — NOT outcomes — and that any self-reported volume or success figures are unverified. "
           "Never imply certified quality or real outcome data.")
    usr = (f'Procedure: {label}{(" near " + location) if location else ""}. Provider asked: "{query}".\n'
           f'Top candidates (already ranked):\n{json.dumps(brief, ensure_ascii=False)}\n'
           'Write the 2-3 sentence recommendation (plain text, no markdown).')
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 400)
    except Exception:
        t = ranking[0]
        bits = ", ".join((t.get("badges") or [])[:3])
        return (f"For {label}, the strongest capability match is {t['name']}"
                + (f" ({t['city']})" if t.get("city") else "")
                + (f", ~{t['km']} km away" if t.get("km") is not None else "")
                + (f" — {bits}" if bits else "")
                + ". Ranked by accreditation + capability, not verified outcomes; treat any self-reported figures as unverified.")


def _procedure_referral(query: str, p: dict, fp: dict | None = None) -> dict:
    proc = p["procedure"]
    label = db.PROCEDURES.get(proc, {}).get("label", proc.title())
    loc = p.get("location") or ""
    anchor = None
    if fp and fp.get("latitude") is not None:
        anchor = (float(fp["latitude"]), float(fp["longitude"]))
    where = f" near {loc}" if loc else ""
    trace = [{"step": "plan", "role": "Planner", "model": MODEL,
              "detail": f"procedure referral: {label}{where}"}]
    rk = db.procedure_ranking(proc, loc, anchor, limit=6)
    ranking = rk.get("ranking", [])
    trace.append({"step": "match", "role": "Retriever", "tool": "procedure_ranking",
                  "detail": f"{rk.get('n_matched', 0)} facilities list {label}"
                            + (f" — nearest {rk.get('pool')} in range" if rk.get("anchored") else "")})
    n_acc = sum(1 for x in ranking if x.get("accredited"))
    trace.append({"step": "score", "role": "Quality proxy", "tool": "accreditation+capability",
                  "detail": f"ranked by NABH/JCI ({n_acc} accredited), specialty on record, technique & scale "
                            "— a capability PROXY, NOT verified outcomes"})
    n_flag = sum(1 for x in ranking if x.get("claims"))
    n_caut = sum(1 for x in ranking if x.get("caution"))
    if n_flag or n_caut:
        bits = []
        if n_flag:
            bits.append(f"{n_flag} with self-reported volume/success figures (surfaced, not scored)")
        if n_caut:
            bits.append(f"{n_caut} list the procedure with no matching specialty on record")
        trace.append({"step": "flag", "role": "Skeptic", "tool": "claims",
                      "detail": "flagged " + "; ".join(bits)})
    answer = _compose_procedure(query, label, loc, ranking)
    trace.append({"step": "compose", "role": "Composer", "model": MODEL,
                  "detail": f"ranked {len(ranking)} destinations for {label}"})
    return {"mode": "procedure", "plan": p, "trace": trace, "procedure": label, "dept": rk.get("dept"),
            "n_matched": rk.get("n_matched", 0), "anchored": rk.get("anchored", False),
            "ranking": ranking, "legend": rk.get("legend", ""), "scored_on": rk.get("scored_on", []),
            "answer": answer}


def _referral_note(query: str, fp: dict, r: dict) -> str:
    """Draft a handoff note the referring provider can hand the patient / send on."""
    dests = []
    if r.get("mode") == "care_team":
        for role in (r.get("care_team") or [])[:4]:
            f = (role.get("facilities") or [None])[0]
            if f:
                dests.append({"for": role["role"], "to": f["name"], "city": f.get("city"), "km": f.get("km")})
    elif r.get("mode") == "procedure":
        # only the top-ranked destination — its (city, distance) are self-consistent;
        # naming runner-ups risks a dirty-coordinate mismatch in the handoff artifact.
        for x in (r.get("ranking") or [])[:1]:
            dests.append({"to": x["name"], "city": x.get("city"), "for": r.get("procedure"),
                          "km": x.get("km"), "why": ", ".join((x.get("badges") or [])[:3])})
    else:
        for s in (r.get("shortlist") or [])[:3]:
            dests.append({"to": s["name"], "city": s.get("city"), "for": s.get("cap"), "why": s.get("why")})
    if not dests:
        return ""
    sys = ("You are a clinician writing a concise REFERRAL NOTE the referring provider hands the patient or sends to "
           "the destination. ~5-7 short lines, plain text (no markdown): From; patient need; where you're referring and "
           "why (cite the specialty/evidence); what to do on arrival / what's enclosed. Use ONLY the destinations given, "
           "which are in PRIORITY ORDER — lead with the FIRST as the recommendation; you may note a closer alternative.")
    usr = (f"Referring provider: {fp['name']}, {fp.get('city') or ''}.\nPatient need (provider's words): \"{query}\".\n"
           f"Recommended destination(s): {json.dumps(dests, ensure_ascii=False)}\nWrite the referral note.")
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 400)
    except Exception:
        d = dests[0]
        return (f"REFERRAL — From {fp['name']}, {fp.get('city') or ''}. Re: {query}. Referring to {d['to']}"
                f"{(' (' + d['city'] + ')') if d.get('city') else ''}{(' — ' + str(d['km']) + ' km') if d.get('km') else ''}. "
                "Please assess and manage; clinical summary enclosed.")


def run(query: str, from_facility: str = "") -> dict:
    fp = db.find_provider(from_facility) if (from_facility or "").strip() else None
    p = plan(query)
    if fp and not p["location"]:
        p["location"] = (fp.get("city") or "").strip()
    if p.get("procedure"):
        r = _procedure_referral(query, p, fp)
    elif p.get("condition", "none") != "none":
        r = care_team_referral(query, p)
    else:
        r = _capability_referral(query, p)
    if fp:
        r["from_provider"] = {"name": fp["name"], "city": fp.get("city"), "state": fp.get("state")}
        r["trace"] = [{"step": "from", "role": "Referring provider", "tool": "find_provider",
                       "detail": f"from {fp['name']}" + (f", {fp.get('city')}" if fp.get("city") else "")}] + (r.get("trace") or [])
        r["referral_note"] = _referral_note(query, fp, r)
        r["trace"].append({"step": "note", "role": "Referral writer", "model": MODEL, "detail": "drafted the referral note"})
    return r
