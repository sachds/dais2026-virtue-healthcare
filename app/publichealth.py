"""Public-health agent — population-scale planning over NFHS-5 demand + our supply.

Two agentic modes (plan over tools → reason → plan + provenance trace):

  IMMUNIZATION CAMPAIGN — find under-immunized districts that have local supply, draft a
    targeted campaign and a health-department referral. Fully real-data.

  OUTBREAK ISOLATION PROTOCOL — given a region + disease (the outbreak SIGNAL — the data
    has no surveillance feed to auto-detect one), assess local isolation capacity and draft
    a containment protocol + escalation. Response-planning given the reported signal.
"""
from __future__ import annotations

import json

from app import agent_tools, llm

MODEL = llm.ENDPOINT


# --------------------------------------------------------------------------- #
def _reason_campaign(targets: list[dict]) -> str:
    brief = [{"district": t["district"], "state": t["state"], "immunization_pct": t["immunization"],
              "penta3_pct": t.get("penta3"), "facilities": t["facilities"],
              "physicians": t["physicians"], "beds": t["beds"]} for t in targets]
    sys = ("You are a public-health planner. Draft a concise, actionable childhood-immunization campaign "
           "over the under-vaccinated districts provided, using ONLY the supply given (the local "
           "facilities / physicians are the delivery network). Name each priority district's coverage gap "
           "and its local capacity to run outreach. Ground every claim in the data; invent no numbers. "
           "Use short headings, prose, and bullet points — NO markdown tables.")
    usr = (f"Under-immunized districts with local supply:\n{json.dumps(brief, ensure_ascii=False)}\n\n"
           "Return a short plan: (1) the 2-3 highest-priority districts and why, (2) how to run the campaign "
           "there using the local facilities/physicians as sites and teams, (3) a one-line referral to the "
           "state/district health department.")
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 700)
    except Exception:
        w = targets[0]
        return (f"Priority: {w['district']}, {w['state']} — only {w['immunization']}% of children fully immunized, "
                f"with {w['facilities']} facilities and {w['physicians']} physicians locally to run outreach. Stand up "
                f"mobile immunization camps at the largest local facilities and refer to the {w['state']} State Health "
                f"Department for cold-chain and vaccine supply.")


def immunization_campaign(region: str = "", n: int = 6) -> dict:
    trace: list[dict] = []
    region = (region or "").strip()
    if region:
        prof = agent_tools.district_profile(region)
        nd = prof.get("nfhs") or {}
        sup = prof.get("supply") or {}
        targets = ([{"district": prof["district"], "state": nd.get("state", ""),
                     "immunization": nd.get("full_immunization"), "penta3": nd.get("penta3"),
                     "bcg": nd.get("bcg"), "insurance": nd.get("insurance"),
                     "facilities": sup.get("facilities", 0), "physicians": sup.get("physicians", 0),
                     "beds": sup.get("beds", 0)}] if nd else [])
        trace.append({"step": "target", "role": "Targeting", "tool": "district_profile",
                      "detail": f"profiled {region}"})
    else:
        targets = agent_tools.under_immunized_districts(limit=n)
        trace.append({"step": "target", "role": "Targeting", "tool": "under_immunized_districts",
                      "detail": f"ranked {len(targets)} under-immunized districts that have local supply"})
    if not targets:
        return {"mode": "immunization", "trace": trace, "targets": [],
                "plan": "No under-immunized districts with local supply found — load the NFHS district data (load_nfhs_district.py)."}
    plan = _reason_campaign(targets)
    trace.append({"step": "plan", "role": "Planner", "model": MODEL,
                  "detail": f"drafted a campaign over {len(targets)} target district(s)"})
    return {"mode": "immunization", "trace": trace, "targets": targets, "plan": plan}


# --------------------------------------------------------------------------- #
def _reason_outbreak(region: str, disease: str, prof: dict) -> str:
    s = prof.get("supply") or {}
    nfhs = prof.get("nfhs") or {}
    top = prof.get("top_facilities") or []
    brief = {"district": region, "disease": disease,
             "supply": {"facilities": s.get("facilities"), "hospitals": s.get("hospitals"),
                        "beds": s.get("beds"), "physicians": s.get("physicians")},
             "top_facilities": [{"name": t["name"], "beds": t["total_beds"], "city": t.get("city")} for t in top],
             "context": {"insurance_pct": nfhs.get("insurance")} if nfhs else {}}
    sys = ("You are a public-health rapid-response planner. Given a suspected disease outbreak in a district "
           "and the LOCAL facility capacity, draft a concise ISOLATION + CONTAINMENT protocol: which facilities "
           "to designate for isolation (favor the largest by beds), the rough isolation capacity, referral "
           "routing for severe cases, and immediate actions (cohorting, contact tracing). Use ONLY the provided "
           "capacity and say plainly if it looks insufficient. End with a health-department escalation line. Note "
           "that outbreak DETECTION needs a surveillance feed not present here — this is the response to a reported signal. "
           "Use short headings, prose, and bullet points — NO markdown tables.")
    usr = f"Suspected outbreak:\n{json.dumps(brief, ensure_ascii=False)}\n\nReturn the isolation / containment protocol."
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 800)
    except Exception:
        names = ", ".join(t["name"] for t in top[:2]) or "the largest local hospital"
        return (f"Designate {names} as isolation centre(s) for the suspected {disease} outbreak in {region} "
                f"({s.get('beds', 0)} beds across {s.get('hospitals', 0)} hospitals locally). Cohort suspected cases, "
                f"route severe cases to the highest-bed facility, begin contact tracing, and escalate to the district/"
                f"state Health Department for surveillance confirmation and resources.")


def _reason_escalation(district: str, condition: str, prof: dict) -> str:
    nfhs = prof.get("nfhs") or {}
    brief = {"district": district, "condition": condition,
             "indicators": {"anaemia_child": nfhs.get("anemia"), "stunting_child": nfhs.get("stunting"),
                            "diabetes": nfhs.get("diabetes"), "hypertension": nfhs.get("hypertension"),
                            "insurance": nfhs.get("insurance"), "institutional_birth": nfhs.get("institutional_birth"),
                            "full_immunization": nfhs.get("full_immunization")},
             "supply": prof.get("supply")}
    sys = ("You are a public-health coordinator. A district shows a high disease burden. Draft a concise ESCALATION "
           "that makes the problem visible to the organizations that can intervene — name the RIGHT bodies for THIS "
           "burden (e.g. for child malnutrition / anaemia+stunting: WHO, UNICEF, the state ICDS + Health Department, "
           "and relevant nutrition NGOs), say what each should do, and which local facilities deliver it. Ground every "
           "claim in the indicators provided; invent no numbers. Use short headings and bullet points — NO tables.")
    usr = (f"High-burden district:\n{json.dumps(brief, ensure_ascii=False)}\n\n"
           "Draft the multi-organization escalation + intervention, ending with who to notify first.")
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 750)
    except Exception:
        return (f"Escalate the {condition} burden in {district} to the State Health Department and ICDS as the first "
                f"responders, with WHO and UNICEF for technical + supply support and local nutrition NGOs for "
                f"community delivery, using the district's existing facilities as the delivery network.")


def escalate_burden(district: str, condition: str = "stunting") -> dict:
    district = (district or "").strip()
    trace: list[dict] = []
    prof = agent_tools.district_profile(district)
    nd = prof.get("nfhs") or {}
    trace.append({"step": "assess", "role": "Assessor", "tool": "district_profile",
                  "detail": f"{district}: {nd.get('anemia', '?')}% child anaemia, {nd.get('stunting', '?')}% stunting"})
    plan = _reason_escalation(district, condition, prof)
    trace.append({"step": "escalate", "role": "Coordinator", "model": MODEL,
                  "detail": "drafted a multi-organization escalation (WHO / NGO / government)"})
    return {"mode": "escalation", "district": district, "condition": condition, "trace": trace,
            "profile": prof, "plan": plan}


def outbreak_protocol(region: str, disease: str) -> dict:
    region, disease = (region or "").strip(), (disease or "disease").strip()
    trace: list[dict] = []
    prof = agent_tools.district_profile(region)
    sup = prof.get("supply") or {}
    trace.append({"step": "assess", "role": "Assessor", "tool": "district_profile",
                  "detail": f"assessed isolation capacity in {region or '—'}: "
                            f"{sup.get('hospitals', 0)} hospitals, {sup.get('beds', 0)} beds"})
    plan = _reason_outbreak(region, disease, prof)
    trace.append({"step": "plan", "role": "Protocol", "model": MODEL,
                  "detail": "drafted isolation + containment protocol"})
    return {"mode": "outbreak", "region": region, "disease": disease, "trace": trace,
            "profile": prof, "plan": plan}
