#!/usr/bin/env python3
"""Trust-signal extraction. For each facility, ask a Databricks-served LLM whether
it provides each capability (icu, maternity, emergency, oncology, trauma, nicu),
using ONLY the facility's evidence text, and to quote EXACT snippets as evidence
and be honest about uncertainty. Results upsert into Lakebase `trust_signals`.

Resumable: only processes facilities that don't yet have signals.
Usage:  python extract.py [N]      # process N facilities (default 200); 'all' for everything
Env:    LAKEBASE_URL  (+ a Databricks profile for serving; default 'lakecode')
"""
from __future__ import annotations
import json, os, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg.types.json import Json
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

PROFILE = os.environ.get("DBX_PROFILE", "lakecode")
ENDPOINT = os.environ.get("DBX_LLM_ENDPOINT", "databricks-gpt-5-5")
CAPS = ["icu", "maternity", "emergency", "oncology", "trauma", "nicu"]
WORKERS = int(os.environ.get("EXTRACT_WORKERS", "8"))

SYSTEM = (
    "You assess whether an Indian healthcare facility can perform specific clinical "
    "capabilities, using ONLY the provided evidence text. Never use outside knowledge, "
    "and never assume a facility has a capability just because it is a 'hospital'. Quote "
    "EXACT snippets as evidence. Be honest about uncertainty: generic claims like 'all "
    "specialties', 'multi-specialty', or 'world-class' are WEAK evidence for any specific "
    "capability, not strong."
)

USER_TMPL = """FACILITY: {name}  (type: {facility_type}, operator: {operator_type})
EVIDENCE:
description: {description}
specialties: {specialties}
procedure: {procedure}
equipment: {equipment}
capability: {capability}

Assess these capabilities: icu, maternity, emergency, oncology, trauma, nicu.
Signal definitions:
- strong: explicit, specific evidence this facility provides the capability (names the unit/service/specialty/equipment).
- partial: indirect or adjacent evidence (a closely related specialty/procedure) but not explicit.
- weak: only vague, generic, or suspicious mention with nothing specific.
- none: no evidence at all.

Return STRICT JSON, one entry per capability, e.g.:
{{"icu": {{"signal": "strong", "confidence": 0.0, "evidence": [{{"field": "specialties", "snippet": "exact quote"}}], "rationale": "one short sentence"}}, ...}}
Rules: snippets must be EXACT substrings of the evidence above; if signal is "none", evidence is []. Output JSON only."""

_w = WorkspaceClient(profile=PROFILE)


def _clean(v) -> str:
    return (v or "").strip() if isinstance(v, str) else (v or "")


def evaluate(fac: dict) -> dict | None:
    user = USER_TMPL.format(
        name=_clean(fac["name"]), facility_type=_clean(fac["facility_type"]),
        operator_type=_clean(fac["operator_type"]), description=_clean(fac["description"])[:2000],
        specialties=_clean(fac["specialties"])[:1500], procedure=_clean(fac["procedure"])[:1500],
        equipment=_clean(fac["equipment"])[:1000], capability=_clean(fac["capability"])[:1500],
    )
    for attempt in range(2):
        try:
            resp = _w.serving_endpoints.query(
                name=ENDPOINT, max_tokens=1500,
                messages=[ChatMessage(role=ChatMessageRole.SYSTEM, content=SYSTEM),
                          ChatMessage(role=ChatMessageRole.USER, content=user)],
            )
            text = resp.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1].removeprefix("json").strip()
            return json.loads(text)
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                print(f"  ! {fac['id']} failed: {str(e)[:100]}")
                return None
            time.sleep(1)


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "200"
    limit = None if arg == "all" else int(arg)
    url = os.environ["LAKEBASE_URL"].replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(url, row_factory=psycopg.rows.dict_row) as pg, pg.cursor() as c:
        # EXTRACT_ORDER=random → geographically representative sample (for the Track 2 map);
        # default = richest-evidence first (for the Track 1 facility demo).
        order = "random()" if os.environ.get("EXTRACT_ORDER") == "random" else \
                "length(coalesce(f.description,'')||coalesce(f.specialties,'')) DESC"
        c.execute(f"""SELECT f.id, f.name, f.facility_type, f.operator_type, f.description,
                             f.specialties, f.procedure, f.equipment, f.capability
                      FROM facilities f
                      WHERE NOT EXISTS (SELECT 1 FROM trust_signals t WHERE t.facility_id = f.id)
                      ORDER BY {order}
                      {('LIMIT %d' % limit) if limit else ''}""")
        todo = c.fetchall()
    print(f"extracting trust signals for {len(todo)} facilities via {ENDPOINT} ({WORKERS} workers)")

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex, psycopg.connect(url) as pg:
        for fac, result in zip(todo, ex.map(evaluate, todo)):
            if not result:
                continue
            ts = int(time.time())
            with pg.cursor() as c:
                for cap in CAPS:
                    r = result.get(cap) or {}
                    sig = r.get("signal", "none") if r.get("signal") in ("strong", "partial", "weak", "none") else "none"
                    c.execute(
                        """INSERT INTO trust_signals (id, facility_id, capability, signal, confidence,
                               evidence, rationale, model, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (facility_id, capability) DO UPDATE SET
                               signal=EXCLUDED.signal, confidence=EXCLUDED.confidence,
                               evidence=EXCLUDED.evidence, rationale=EXCLUDED.rationale,
                               model=EXCLUDED.model, created_at=EXCLUDED.created_at""",
                        ("ts_" + uuid.uuid4().hex[:14], fac["id"], cap, sig,
                         float(r.get("confidence") or 0.0), Json(r.get("evidence") or []),
                         (r.get("rationale") or "")[:500], ENDPOINT, ts),
                    )
            pg.commit()
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(todo)}")
    print(f"done: {done} facilities scored")


if __name__ == "__main__":
    main()
