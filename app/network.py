"""Care-Network analysis — coordinating Copilot instances into a system-level view.

A single Referral Copilot answers one provider's question ("where do I send THIS
patient?"). This module coordinates that resolution across EVERY facility in a region
and aggregates the result into something no single instance can see: the inferred
referral network, the chokepoints the whole region depends on, and — by crossing the
load map against the trust substrate — the single-points-of-failure that are *also*
only weakly evidenced.

It is the same governed mesh, run as a fleet:
  COORDINATE  referral_network — resolve each facility's nearest trusted destination
  FAN-OUT     N facilities routed to a handful of destinations (the Copilot, ×N)
  AGGREGATE   destination in-degree = load = structural dependency
  SKEPTIC     cross-check the top chokepoint's OWN evidence (facility_evidence)
  SYNTHESIZE  the systemic-risk finding + what to do about it

mcp_server.py mounts db.referral_network as a tool, so an Omnigent harness drives the
exact same coordination over MCP.
"""
from __future__ import annotations

from app import agent_tools, db, llm

MODEL = llm.ENDPOINT


def _synthesize(cap: str, state: str, net: dict, top: dict, skeptic: dict) -> str:
    sys = ("You are a health-system analyst. You are shown the INFERRED referral network for one capability in one "
           "Indian state: how many facilities lack it and which few destinations they all route to, plus the top "
           "chokepoint's OWN cited evidence. In 2-3 sentences, state the systemic risk plainly — how concentrated the "
           "dependency is, and why a chokepoint that is itself only PARTIALLY evidenced (or the sole destination) is a "
           "single point of failure for the whole region. End with the one action a health department should take. "
           "Be concrete with the numbers. Never imply we have patient or outcome data — this is supply + geography.")
    usr = (f"Capability: {cap.upper()} · State: {state}\n"
           f"{net['n_referrer']} facilities have no trusted {cap.upper()}; only {net['n_dest']} trusted destinations serve them.\n"
           f"Top chokepoint: {top['name']} ({top.get('city') or ''}) — carries {top['share']}% of referrals "
           f"({top['in_degree']} facilities), avg {top.get('avg_km')} km away, its own {cap.upper()} evidence is "
           f"'{skeptic.get('signal') or 'none'}'"
           + (f" (cited: \"{skeptic['snippet']}\")" if skeptic.get("snippet") else "") + ".\n"
           f"{net.get('n_spof', 0)} of the destinations are flagged single-points-of-failure.\n"
           "Write the 2-3 sentence systemic-risk finding + the one recommended action (plain text, no markdown).")
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 400)
    except Exception:
        return (f"{top['share']}% of {state}'s {cap.upper()} referrals — {top['in_degree']} facilities — funnel to "
                f"{top['name']}, whose own {cap.upper()} evidence is {skeptic.get('signal') or 'unverified'}. With only "
                f"{net['n_dest']} trusted destinations for {net['n_referrer']} referrers, the network has little "
                f"fallback: if this node is saturated or its claim doesn't hold, those facilities have nowhere to send "
                f"a critical patient. Action: verify and shore up {cap.upper()} capacity at the top chokepoints first.")


def network_analysis(capability: str, state: str) -> dict:
    """Run the coordinated fleet over `state` for `capability` and return the network +
    the synthesized systemic-risk finding, with a full trace of the coordination."""
    net = db.referral_network(capability, state)
    cap = net["capability"]
    trace = [{"step": "coordinate", "role": "Coordinator", "tool": "referral_network",
              "detail": f"resolved each facility's nearest trusted {cap.upper()} from its own vantage point across {state}"}]

    if net.get("no_destination"):
        net["trace"] = trace + [{"step": "result", "role": "Network analyst", "tool": "in-degree",
                                 "detail": f"no trusted {cap.upper()} supply anywhere in {state} — the entire state is a gap"}]
        net["finding"] = (f"{state} has NO facility with trusted {cap.upper()} evidence — its {net['n_referrer']} "
                          f"facilities have no in-state destination at all. This is a whole-state {cap.upper()} desert.")
        net["skeptic"] = None
        return net

    trace.append({"step": "fanout", "role": "Referral fleet", "tool": "copilot ×N",
                  "detail": f"{net['n_referrer']} facilities with no trusted {cap.upper()} routed to "
                            f"{net['n_dest']} destination{'s' if net['n_dest'] != 1 else ''}"})
    bn = net["bottlenecks"]
    top = bn[0]
    trace.append({"step": "aggregate", "role": "Network analyst", "tool": "in-degree",
                  "detail": f"top chokepoint {top['name']} carries {top['share']}% of referrals "
                            f"({top['in_degree']} facilities); {net.get('n_spof', 0)} single-point(s) of failure flagged"})

    # SKEPTIC — the chokepoint everyone depends on: does its OWN evidence hold up?
    ev = agent_tools.facility_evidence(top["id"])
    capev = next((x for x in (ev.get("capabilities") or []) if x.get("capability") == cap), None)
    snippet = (capev.get("evidence") or [None])[0] if capev else None
    skeptic = {"name": top["name"], "trust": top["trust"],
               "signal": capev.get("signal") if capev else None, "snippet": snippet}
    trace.append({"step": "skeptic", "role": "Skeptic", "model": MODEL,
                  "detail": f"cross-checked the chokepoint's own {cap.upper()} evidence — "
                            f"signal '{skeptic['signal'] or 'none'}'"
                            + (" → high-load node on partial evidence" if skeptic["signal"] == "partial" else "")})

    finding = _synthesize(cap, state, net, top, skeptic)
    trace.append({"step": "synthesize", "role": "Composer", "model": MODEL,
                  "detail": "wrote the systemic-risk finding + recommended action"})

    net["trace"] = trace
    net["finding"] = finding
    net["skeptic"] = skeptic
    net["top"] = top
    return net


def _synthesize_siting(cap: str, state: str, si: dict, top: dict) -> str:
    relief = top.get("relieves_choke") or 0
    choke_name = si.get("choke", {}).get("name", "")
    impact = (f"If resourced as a trusted {cap.upper()} destination: {top['captured']} facilities gain a closer "
              f"option, ~{top['km_saved_avg']} km saved each ({top['km_saved_total']} km total). ")
    impact += (f"It pulls {relief} referrals off the current chokepoint {choke_name}."
               if relief else
               f"These facilities currently sit ~{top['km_saved_avg']} km from the nearest trusted {cap.upper()} — "
               "an underserved cluster with no destination nearby.")
    sys = ("You are a health-system planner advising where to place ONE new resource (a specialist team, ICU kit, "
           "etc.) to relieve a referral bottleneck or reach an underserved cluster. In 2-3 sentences, make the "
           "recommendation concretely — name the facility and what to resource, and the impact in facilities + km. "
           "Use ONLY the facts given; do NOT claim the facilities route to a named chokepoint unless told so. This is "
           "a supply/geography optimization; do not imply patient or outcome data.")
    usr = (f"Capability: {cap.upper()} · State: {state}\n"
           f"Recommended site: {top['name']} ({top.get('city') or ''}), {top.get('beds') or 0} beds.\n"
           f"{impact}\nWrite the 2-3 sentence siting recommendation (plain text, no markdown).")
    try:
        return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": usr}], 360)
    except Exception:
        tail = (f"and pull {relief} referrals off {choke_name or 'the chokepoint'}"
                if relief else f"reaching an underserved cluster ~{top['km_saved_avg']} km from the nearest {cap.upper()}")
        return (f"Highest-impact intervention: resource a trusted {cap.upper()} at {top['name']}"
                f"{(' (' + top['city'] + ')') if top.get('city') else ''}"
                f"{(', ' + str(top['beds']) + ' beds') if top.get('beds') else ''}. It would give "
                f"{top['captured']} facilities a closer {cap.upper()}, save ~{top['km_saved_avg']} km each, {tail}.")


def siting_analysis(capability: str, state: str) -> dict:
    """Phase 2 — the mission-siting optimizer over the network: rank existing facilities
    by the counterfactual impact of resourcing them, and synthesize the recommendation."""
    si = db.siting_impact(capability, state)
    cap = si["capability"]
    sites = si.get("sites", [])
    trace = [{"step": "candidates", "role": "Planner", "tool": "siting_impact",
              "detail": f"evaluated {si.get('n_candidates', 0)} existing {state} facilities as candidate "
                        f"{cap.upper()} sites — counterfactual re-routing of {si.get('n_referrer', 0)} referrers"}]
    if not sites:
        si["trace"] = trace
        si["recommendation"] = (f"No high-impact {cap.upper()} site found in {state} — too few referrers or "
                                "destinations to optimize over.")
        return si
    top = sites[0]
    trace.append({"step": "counterfactual", "role": "Optimizer", "tool": "re-route",
                  "detail": f"best site {top['name']} → {top['captured']} facilities gain a closer {cap.upper()}, "
                            f"~{top['km_saved_avg']} km saved each"})
    if si.get("choke") and top.get("relieves_choke"):
        trace.append({"step": "relief", "role": "Network analyst", "tool": "load-relief",
                      "detail": f"pulls {top['relieves_choke']} referrals off the chokepoint {si['choke']['name']}"})
    trace.append({"step": "synthesize", "role": "Composer", "model": MODEL,
                  "detail": "wrote the siting recommendation"})
    si["trace"] = trace
    si["recommendation"] = _synthesize_siting(cap, state, si, top)
    si["top"] = top
    return si
