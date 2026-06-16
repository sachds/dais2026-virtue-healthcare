# Medical Desert Planner — a trust‑and‑agents platform for healthcare‑for‑good

**Databricks Apps & Agents Hackathon for Good · DAIS 2026 · Virtue Foundation healthcare data**

One Databricks App on **Lakebase** that turns 10,000 messy Indian healthcare facility
records into **evidence‑attached, geography‑aware, accountable health decisions** — for
individual patients *and* whole communities. It started as the four challenge tracks on one
trust‑signal substrate, and grew a fleet of **governed agents** on top: a referral copilot
and a public‑health planner that show their work, cite their evidence, and are honest about
what the data can't say.

> Live app: `https://facility-trust-desk-5528334136090880.aws.databricksapps.com`
> (Databricks SSO required.) · Built live during the event — see the commit history.

## What it does — five panes, one Lakebase substrate

| Pane | Answers | How |
|---|---|---|
| **◧ Gap map** *(T2 · landing)* | *Where are the deserts?* | A **geographic map** (districts plotted at their lat/long, self‑forming India) **and** a state heatmap, colored by trusted supply for a capability — overlaid with **NFHS‑5 health burden** so the headline is the *dangerous shortfall* (burden × thin supply). District grain surfaces real gaps the state level hides (ICU: 13 gap districts). |
| **🏥 Trust Desk** *(T1)* | *Can this facility do what it claims?* | Per‑capability signal (strong/partial/weak/none) with the **exact source text quoted** + a **cardinality cross‑check** — a "strong ICU" claim with **0 ICU specialists on record** is flagged as uncorroborated. Analyst **override** persists to Lakebase. |
| **✦ Referral Copilot** *(T3)* | *Where should this patient go?* | A **governed multi‑agent mesh** (plan → retrieve → scrutinize → **adversarial skeptic** → **policy gate** → compose) that recommends only **vetted** facilities and shows what it **blocked**. For a chronic condition it assembles a **care team** (a diabetic → endocrinology **+ dentist + eye doctor + nephrology**, nearest by distance) and **escalates** on ≥2 visits/month. |
| **⚕ Public Health** *(new)* | *What's good for the community?* | Population‑scale agents: an **immunization campaign** (find under‑vaccinated districts with local supply → plan it), an **outbreak isolation protocol** (designate isolation facilities from real bed capacity), **disease‑burden benchmarks** by geography vs a national baseline (anaemia × stunting together), and an **agentic escalation** that drafts a WHO / NGO / government referral for a high‑burden area. |
| **✓ Data Readiness** *(T4)* | *What must be fixed first?* | Field‑coverage + weak‑claim profile, an **over‑claim review queue** (a dental clinic claiming oncology), **clinical classification & capacity** (specialties/procedures → 7 service lines, beds by line, "facilities must have beds / providers must have a specialty"), and supply **by district**. |

## How it works

```
Virtue Foundation data + India Post PIN + NFHS-5  (Databricks Marketplace / Delta Sharing)
  → load_facilities.py   → Lakebase facilities (10,088)
  → load_nfhs.py / load_nfhs_district.py → nfhs_state, nfhs_district (demand: burden, immunization, NCD)
  → load_pincode.py      → pincode (PIN→district→state); stamps district onto each facility (96%)
  → classify_facilities.py (app/taxonomy.py) → facility_services (service lines, beds, cap_specialists)
  → extract.py (GPT-5.5 on Databricks Model Serving) → trust_signals
       {signal, confidence, EXACT cited evidence snippets, rationale}  ← evidence-grounded, uncertainty-honest
  → FastAPI Databricks App (app/) serves the five panes, persists reviews
  → AGENTS on Claude Haiku 4.5, all plan→reason→trace with provenance:
       app/copilot.py      governed referral mesh + care-team   (control = app/policy.py)
       app/publichealth.py immunization / outbreak / burden-escalation
       tools = app/agent_tools.py (the substrate) — also exposed over MCP (mcp_server.py)
       the same loop runs under real OMNIGENT (agents/referral) → composition + control, verified
```

**Design spine:** trust signals are *precomputed* offline so the app stays instant; the LLM uses
**only the facility's own text** (generic "all specialties" → *weak*, not strong); governance is **code,
not prompt** (the model can't recommend past `policy.py`); every agent **shows its work** and cites
evidence; and the data is treated as **claims to verify, not ground truth** — overrides are first‑class.

## Meets the brief (and then some)

- ✅ **Databricks App** on ✅ **Lakebase** · ✅ non‑technical workflow across five panes
- ✅ **Cites the source text** for every claim, score, recommendation, campaign, and escalation
- ✅ **Communicates uncertainty** (confidence + signal levels + cardinality + "claims to verify")
- ✅ **Persists user actions** (overrides / notes / shortlists / decisions → Lakebase `reviews`)
- ✅ **Agents** — a governed referral mesh + public‑health agents, runnable under **Omnigent** over an MCP

## Repo layout

```
app/  FastAPI app (main.py routes, db.py Lakebase, static/ UI)
  copilot.py       governed referral mesh + care-team (plan→…→govern→compose)
  publichealth.py  immunization campaign / outbreak protocol / burden escalation agents
  policy.py        governance — trust rules in code (the control pillar)
  agent_tools.py   the substrate as tools  ·  taxonomy.py  service-line classification
  llm.py           Databricks Model Serving client (Claude Haiku 4.5)
mcp_server.py      the tools over MCP — what an Omnigent agent mounts (dual stdio/http)
agents/referral/   Omnigent spec + run script + a verified sample run
db/schema.sql      Lakebase: facilities, trust_signals, reviews, nfhs_state, nfhs_district,
                   facility_services, pincode
load_facilities / load_nfhs / load_nfhs_district / load_pincode / classify_facilities / extract.py
scripts/  serve.sh (local) · deploy_databricks.sh (App) · run_referral_agent.sh (Omnigent)
```

## Run it

```bash
./scripts/serve.sh              # local on :8099 (needs .env: LAKEBASE_URL + a Databricks profile)
python load_facilities.py       # Marketplace → Lakebase
python load_nfhs.py && python load_nfhs_district.py && python load_pincode.py
python classify_facilities.py   # service lines, capacity, cardinality
python extract.py 2500          # representative trust-signal sample
./scripts/deploy_databricks.sh  # deploy as a Databricks App
```

## Data

Virtue Foundation `facilities` (10,088), the **India Post PIN directory**, and **NFHS‑5** district
health indicators — all via Databricks Marketplace (Government Open Data License, India). Evidence
fields are **claims to verify**, not truth.

## Honest notes — what this data can and can't do

- **Trust signals** are precomputed on a representative sample during the event (same `extract.py` run for the full 10k).
- **No patient‑level data** in the set — so patient‑finding, the visit‑count escalation, and cancer‑patient
  rates are scenario/input‑driven, not tracked. The care‑team and referral work on supply + the given context.
- **No surveillance time‑series** — so outbreak *detection* isn't possible; the isolation protocol responds to a
  *reported* signal. Both go live the moment an external feed (registry / surveillance) is connected.
- **No payer network directory** — insurance shows as NFHS *coverage %*, not in‑network participation.
- Geographic work is **district** grain via the PIN bridge (96% of facilities mapped); the desert map plots
  real district‑level gaps the state level hides.
