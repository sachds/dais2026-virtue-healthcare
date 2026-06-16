"""Governance policy — the CONTROL pillar.

Trust rules enforced in *code*, not in a prompt: the agent can reason however it
likes, but a referral only reaches the planner if it passes these. This is the
same function-policy pattern Omnigent runs over tool results (cf.
commons/commons_policy/capture.py) — here it gates referral recommendations
against the evidence-backed trust signals so a model can't talk its way into
recommending an unverified or over-claimed capability.

Verdicts per (facility, capability) the agent wants to surface:
  allow  — credible evidence (strong/partial), no red flag
  flag   — surfaced but with a MANDATORY caution (over-claim / blanket claim / skeptic doubt)
  block  — never surfaced (no credible evidence, or the skeptic refuted it)
"""
from __future__ import annotations

HIGH_ACUITY = {"icu", "trauma", "oncology", "nicu"}
HOSPITAL_TYPES = {"hospital", "medicalcollege", "nursinghome", "medicalcenter"}
CREDIBLE = {"strong", "partial"}


def evaluate(cap: str, signal: str | None, facility_type: str | None,
             n_strong_caps: int = 0, skeptic: dict | None = None) -> dict:
    """The rule set. Returns {verdict, reasons}."""
    ftype = (facility_type or "").lower()
    # 1 · no credible evidence → block (never recommend a weak/absent claim)
    if signal not in CREDIBLE:
        return {"verdict": "block",
                "reasons": [f"{cap}: only '{signal or 'no'}' evidence — not credible enough to refer to"]}
    # 2 · the skeptic refuted the claim from its own evidence → block
    if skeptic and skeptic.get("verdict") == "refute":
        return {"verdict": "block",
                "reasons": [f"{cap}: skeptic refuted — {skeptic.get('why') or 'evidence does not support the claim'}"]}
    reasons: list[str] = []
    # 3 · over-claim by facility type (a clinic/dental claiming strong ICU/trauma/…)
    if signal == "strong" and cap in HIGH_ACUITY and ftype and ftype not in HOSPITAL_TYPES:
        reasons.append(f"a '{facility_type}' claiming strong {cap} fits the over-claim pattern — verify before referral")
    # 4 · blanket claim — strong on (almost) everything is a red flag
    if n_strong_caps >= 5:
        reasons.append(f"claims strong on {n_strong_caps}/6 capabilities — blanket-claim pattern, treat with skepticism")
    # 5 · skeptic raised doubt (not a full refutation)
    if skeptic and skeptic.get("verdict") == "doubt" and skeptic.get("why"):
        reasons.append(f"{cap}: {skeptic['why']}")
    return {"verdict": "flag" if reasons else "allow", "reasons": reasons}


def gate(candidates: list[dict], caps: list[str],
         skeptic_by_id: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Apply the policy to each candidate's best requested capability.
    Returns (passed, blocked); each entry carries cap/signal/snippet + verdict + reasons.
    `skeptic_by_id` maps facility_id → {cap: {verdict, why}} from the skeptic pass."""
    skeptic_by_id = skeptic_by_id or {}
    passed, blocked = [], []
    for c in candidates:
        sigs = c.get("signals") or {}
        # blanket-claim needs strong count across ALL caps; the copilot attaches
        # n_strong_all after scrutinizing (facility_evidence). Fall back to the
        # requested-cap signals when called standalone.
        n_strong = c.get("n_strong_all")
        if n_strong is None:
            n_strong = sum(1 for s in sigs.values() if s.get("signal") == "strong")
        best = next(((cap, sigs[cap]) for cap in caps
                     if sigs.get(cap) and sigs[cap].get("signal") in CREDIBLE), None)
        if not best:
            blocked.append({**c, "cap": None, "verdict": "block",
                            "reasons": ["no requested capability has credible evidence here"]})
            continue
        cap, s = best
        sk = (skeptic_by_id.get(c["id"]) or {}).get(cap)
        v = evaluate(cap, s.get("signal"), c.get("facility_type"), n_strong, sk)
        rec = {"id": c["id"], "name": c.get("name"), "city": c.get("city"),
               "state": c.get("state"), "facility_type": c.get("facility_type"),
               "cap": cap, "signal": s.get("signal"), "snippet": s.get("snippet"),
               "verdict": v["verdict"], "reasons": v["reasons"]}
        (blocked if v["verdict"] == "block" else passed).append(rec)
    return passed, blocked
