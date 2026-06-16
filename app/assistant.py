"""Ask Care Compass — the app-wide assistant.

ONE conversational agent, available on every page. It reads the current Focus
(region · capability · facility) and the page you're on, routes your request to the
right capability over the SHARED tool substrate (app/agent_tools.py — the exact tools
mcp_server.py exposes to an Omnigent agent), runs it, and answers with its work.

So the assistant isn't a new brain bolted on — it's the same governed substrate the
Referral Copilot and the Care Network already use, surfaced everywhere. One tool
surface, driven in-process here and by Omnigent's harness offline.
"""
from __future__ import annotations

import json
import re

from app import agent_tools, copilot, db, llm, network, publichealth

MODEL = llm.ENDPOINT
CAPS = db.CAPS

# the capabilities the assistant can route to, with a hint for the router
INTENTS = {
    "network": "show how care flows / the referral network / chokepoints for a capability in a region",
    "route": "balance the load / relieve the chokepoint / redistribute referrals",
    "site": "where to add capacity / site or resource a new facility",
    "circuit": "schedule a visiting specialist / medical-mission circuit",
    "referral": "send or refer a patient somewhere; 'where do I send', a procedure, a care team",
    "trust": "is a facility credible / verify or check a facility's claim / can it really do X",
    "gap": "where is the worst gap / shortfall / medical desert",
    "immunization": "plan an immunization / vaccination campaign",
    "outbreak": "outbreak response / isolation / contain a disease in a district",
    "burden": "disease burden / prevalence / benchmark (diabetes, hypertension, anaemia, stunting)",
}

_KW = [("balance", "route"), ("reroute", "route"), ("redistribut", "route"), ("relieve", "route"),
       ("add capacity", "site"), ("where should", "site"), ("resource", "site"), ("siting", "site"),
       ("circuit", "circuit"), ("visiting", "circuit"), ("mission", "circuit"), ("itinerary", "circuit"),
       ("network", "network"), ("chokepoint", "network"), ("flows", "network"), ("depend", "network"),
       ("credible", "trust"), ("verify", "trust"), ("trust", "trust"), ("can it", "trust"), ("really do", "trust"),
       ("gap", "gap"), ("desert", "gap"), ("shortfall", "gap"), ("underserved", "gap"),
       ("immuniz", "immunization"), ("vaccin", "immunization"), ("campaign", "immunization"),
       ("outbreak", "outbreak"), ("isolat", "outbreak"), ("contain", "outbreak"),
       ("burden", "burden"), ("prevalen", "burden"), ("anaemia", "burden"), ("anemia", "burden"),
       ("stunting", "burden"), ("benchmark", "burden"),
       ("refer", "referral"), ("send", "referral"), ("patient", "referral")]


def _route(query: str, focus: dict, page: str) -> dict:
    foc_fac = focus.get("facility") or {}
    sys = ("You route a healthcare planner's request to ONE capability and extract its parameters. "
           "Capabilities: " + "; ".join(f"{k} = {v}" for k, v in INTENTS.items()) + ". "
           "Clinical capability is one of: icu, maternity, emergency, oncology, trauma, nicu. "
           "Default missing parameters from the current focus + page.")
    usr = (f'Request: "{query}"\nCurrent focus: region={focus.get("region") or "—"}, '
           f'capability={focus.get("capability") or "—"}, facility={foc_fac.get("name") or "—"}\nPage: {page}\n'
           'Return STRICT JSON {"intent":"<' + "|".join(INTENTS) + '>","region":"<state or empty>",'
           '"capability":"<icu|maternity|emergency|oncology|trauma|nicu or empty>",'
           '"facility":"<name or empty>","disease":"<disease or empty>"}.')
    try:
        out = llm.chat_json([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 300)
    except Exception:
        out = {}
    intent = (out.get("intent") or "").strip()
    if intent not in INTENTS:
        intent = ""
    if not intent:
        ql = query.lower()
        intent = next((it for kw, it in _KW if kw in ql), "referral")
    region = (out.get("region") or "").strip() or (focus.get("region") or "")
    cap = (out.get("capability") or "").strip().lower()
    if cap not in CAPS:
        cap = (focus.get("capability") or "")
    facility = (out.get("facility") or "").strip() or (foc_fac.get("name") or "")
    disease = (out.get("disease") or "").strip()
    # deterministic facility grab for "is <Facility>'s X credible?" when the router misses it
    if intent == "trust" and not facility:
        m = re.split(r"['’]s\b", query, maxsplit=1)
        if len(m) > 1:
            cand = re.sub(r"^\s*(is|are|can|does|the|how good is)\s+", "", m[0], flags=re.I).strip()
            if len(cand) >= 3:
                facility = cand
    return {"intent": intent, "region": region, "capability": cap, "facility": facility, "disease": disease}


def _synth(query: str, context: str) -> str:
    sys = ("You are Care Compass's assistant. Answer the planner's question in 2-3 sentences using ONLY the data given. "
           "Be concrete with the numbers. Never imply we have patient or outcome data — this is supply + NFHS-5 demand + "
           "cited claims to verify.")
    usr = f'Question: "{query}"\nData:\n{context}\nAnswer in 2-3 sentences (plain text, no markdown).'
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 350)
    except Exception:
        return ""


def _step(query: str, intent: str, region: str, cap: str, facility: str) -> dict:
    bits = [intent]
    if region:
        bits.append(region)
    if cap:
        bits.append(cap.upper())
    if facility:
        bits.append(facility)
    return {"step": "understand", "role": "Assistant", "model": MODEL,
            "detail": "routed to → " + " · ".join(bits)}


def run(query: str, focus: dict | None = None, page: str = "") -> dict:
    focus = focus or {}
    r = _route(query, focus, page)
    intent, region, cap, facility, disease = (r["intent"], r["region"], r["capability"], r["facility"], r["disease"])
    head = [_step(query, intent, region, cap, facility)]
    capx = cap or "icu"

    try:
        if intent in ("network", "route", "site", "circuit"):
            if not region:
                return {"ok": True, "intent": intent, "title": "Care network",
                        "answer": "Tell me a state (or set a region in Focus) and I'll map its network — e.g. "
                                  "\"balance the ICU load in Bihar\".", "trace": head, "goto": {"view": "network"}}
            fn = {"network": network.network_analysis, "route": network.route_analysis,
                  "site": network.siting_analysis, "circuit": network.circuit_analysis}[intent]
            sub = fn(capx, region)
            answer = sub.get("finding") or sub.get("recommendation") or sub.get("answer") or ""
            label = {"network": "Map the network", "route": "See the routing plan",
                     "site": "See where to add capacity", "circuit": "See the circuit"}[intent]
            return {"ok": True, "intent": intent, "title": f"{capx.upper()} · {region}",
                    "answer": answer, "trace": head + (sub.get("trace") or []),
                    "goto": {"view": "network", "focus": {"region": region, "capability": capx}, "label": label}}

        if intent == "trust":
            prov = db.find_provider(facility) if facility else None
            if not prov and facility:   # fuzzy: try the most distinctive word (e.g. "Fortis")
                word = max(facility.split(), key=len, default="")
                if len(word) >= 4:
                    prov = db.find_provider(word)
            if not prov:
                return {"ok": True, "intent": "trust", "title": "Trust check",
                        "answer": "Name a facility to trust-check (or open one first) — e.g. \"is Fortis Jaipur's ICU "
                                  "claim credible?\".", "trace": head, "goto": {"view": "trust"}}
            ev = agent_tools.facility_evidence(prov["id"])
            ctx = f"Facility: {ev.get('name')} ({ev.get('facility_type')}), {ev.get('city')}.\n" + "\n".join(
                f"- {c['capability']}: {c['signal']} — " + ("; ".join(c.get("evidence") or []) or "no cited text")
                for c in (ev.get("capabilities") or []))
            answer = _synth(query, ctx) or f"{ev.get('name')} — see its cited capability evidence."
            trace = head + [{"step": "evidence", "role": "Investigator", "tool": "facility_evidence",
                             "detail": f"pulled the cited record for {ev.get('name')}"},
                            {"step": "skeptic", "role": "Skeptic", "model": MODEL,
                             "detail": "judged the claim from its own evidence"}]
            return {"ok": True, "intent": "trust", "title": f"Trust check · {prov['name']}", "answer": answer,
                    "trace": trace, "goto": {"view": "trust", "facility": {"id": prov["id"], "name": prov["name"]},
                                             "label": "Open the full record"}}

        if intent == "referral":
            sub = copilot.run(query, facility)
            return {"ok": True, "intent": "referral", "title": "Referral", "answer": sub.get("answer") or "",
                    "trace": head + (sub.get("trace") or []),
                    "goto": {"view": "copilot", "query": query, "from": facility, "label": "Open the Referral Copilot"}}

        if intent == "immunization":
            sub = publichealth.immunization_campaign(region)
            return {"ok": True, "intent": "immunization", "title": "Immunization campaign",
                    "answer": sub.get("plan") or "", "trace": head + (sub.get("trace") or []),
                    "goto": {"view": "publichealth", "label": "Open Public Health"}}

        if intent == "outbreak":
            if not region:
                return {"ok": True, "intent": "outbreak", "title": "Outbreak response",
                        "answer": "Name a district and disease — e.g. \"contain a measles outbreak in Jhansi\".",
                        "trace": head, "goto": {"view": "publichealth"}}
            sub = publichealth.outbreak_protocol(region, disease)
            return {"ok": True, "intent": "outbreak", "title": f"Outbreak · {region}",
                    "answer": sub.get("plan") or "", "trace": head + (sub.get("trace") or []),
                    "goto": {"view": "publichealth", "label": "Open Public Health"}}

        if intent == "burden":
            b = db.disease_benchmarks()
            if not b.get("available"):
                return {"ok": True, "intent": "burden", "title": "Disease burden",
                        "answer": "The NFHS district benchmarks aren't loaded.", "trace": head}
            ctx = "National baselines + worst districts:\n" + "\n".join(
                f"- {c['label']}: national {c['national']}%, worst "
                + ", ".join(f"{w['district']} {w['v']}%" for w in (c.get('worst') or [])[:3])
                for c in (b.get("conditions") or []))
            answer = _synth(query, ctx)
            return {"ok": True, "intent": "burden", "title": "Disease burden", "answer": answer,
                    "trace": head + [{"step": "benchmark", "role": "Epidemiology", "tool": "disease_benchmarks",
                                      "detail": "national baselines + the worst districts above them"}],
                    "goto": {"view": "publichealth", "label": "Open Public Health"}}

        # gap (default analytical)
        g = db.desert_grid()
        risks = g.get("top_risks") or []
        ctx = "Highest-risk shortfalls (burden × thin trusted supply):\n" + "\n".join(
            f"- {x['capability'].upper()} in {x['state']}: {x['trusted']} of {x['n_scored']} trusted "
            f"(need {x.get('need_index')})" for x in risks[:6])
        answer = _synth(query, ctx)
        items = [{"capability": x["capability"], "state": x["state"], "trusted": x["trusted"],
                  "n_scored": x["n_scored"]} for x in risks[:4]]
        return {"ok": True, "intent": "gap", "title": "Worst gaps", "answer": answer, "items": items,
                "trace": head + [{"step": "gap", "role": "Planner", "tool": "desert_grid",
                                  "detail": "ranked shortfalls by burden × thin trusted supply"}],
                "goto": {"view": "desert", "label": "Open the Gap map"}}
    except Exception as e:  # noqa: BLE001 — never let the assistant 500; degrade to a message
        return {"ok": False, "intent": intent, "title": "Assistant",
                "answer": f"I hit an error running that ({type(e).__name__}). Try rephrasing, or use the pane directly.",
                "trace": head}
