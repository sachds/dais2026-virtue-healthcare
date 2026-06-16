# Medical Desert Planner — Facility Trust Desk

**Databricks Apps & Agents Hackathon for Good · DAIS 2026 · Virtue Foundation healthcare data**

One Databricks App on **Lakebase** that turns 10,000 messy Indian healthcare facility
records into evidence‑attached, uncertainty‑aware decisions a non‑technical planner
can trust — addressing **all four challenge tracks as four lenses on one trust‑signal
substrate.**

> Live app: `https://facility-trust-desk-5528334136090880.aws.databricksapps.com`
> (Databricks SSO required.)

## What it does

| View | Track | What it answers |
|---|---|---|
| **Gap map** (landing) | **T2 — Medical Desert Planner** | *Where is the dangerous shortfall?* A state × capability map that separates **confirmed gaps** (enough evaluated, none trusted) from **data‑poor regions**, shades supply by how *thin* it is, and overlays **NFHS‑5 health burden** — so the headline is the **highest‑RISK shortfalls** (burden × thin trusted supply), not just empty cells. |
| facility detail | **T1 — Facility Trust Desk** | *Can this facility do what it claims?* Per‑capability trust signal (strong / partial / weak / none) with the **exact source text quoted**, a confidence score, and analyst **override**. |
| **Ask the Copilot** | **T3 — Referral Copilot** | *Where should a patient go?* A live agent: a need + place → plans → retrieves from Lakebase → reasons → an **evidence‑cited shortlist**. |
| **Data readiness** | **T4 — Data Readiness Desk** | *What must be fixed first?* Field‑coverage profile, weak/suspicious‑claim split, and an **over‑claim review queue** (e.g. a dental clinic claiming oncology) → verify & override. |

## How it works

```
Virtue Foundation data (Databricks Marketplace / Delta Sharing)
  → load_facilities.py → Lakebase `facilities` (10,088 records)
  → load_nfhs.py → Lakebase `nfhs_state` (NFHS-5 district indicators → state-level demand)
  → extract.py (GPT-5.5 on Databricks Model Serving) → Lakebase `trust_signals`
       {signal, confidence, EXACT cited evidence snippets, rationale}  ← evidence-grounded, uncertainty-honest
  → FastAPI Databricks App (app/) serves the four views, persists `reviews`
       Track 2 overlays demand: high-RISK shortfall = health burden × thin trusted supply
  → Referral Copilot (app/copilot.py) reasons live on Claude Haiku 4.5
```

**Design choices:** trust signals are *precomputed* offline (10k × 6 capabilities) so the
app stays instant and cheap; the LLM is told to use **only the facility's own text** (no
outside knowledge, generic "all specialties" claims scored *weak* not *strong*); and the
human **override is first‑class** — the data is *claims to verify, not ground truth*.

## Meets the brief

- ✅ Runs as a **Databricks App** · ✅ uses **Lakebase** · ✅ non‑technical workflow
- ✅ **Cites the underlying facility text** for every claim, score, and recommendation
- ✅ **Communicates uncertainty** (confidence + signal levels + "claims to verify" banner)
- ✅ **Persists user actions** (overrides / notes / shortlists / review decisions → Lakebase `reviews`)

## Repo layout

```
app/            FastAPI app — main.py (routes), db.py (Lakebase), copilot.py + llm.py (the agent), static/ (UI)
db/schema.sql   Lakebase tables: facilities, trust_signals, nfhs_state, reviews
load_facilities.py   Delta Sharing (Marketplace) → Lakebase
load_nfhs.py    NFHS-5 district indicators → state demand (Lakebase nfhs_state)
extract.py      GPT-5.5 trust-signal extraction (resumable; EXTRACT_ORDER=random for a representative map)
scripts/        serve.sh (local), deploy_databricks.sh (Databricks App)
```

## Run it

```bash
# local (needs a .env with LAKEBASE_URL + Databricks profile auth)
./scripts/serve.sh                      # http://localhost:8099
python load_facilities.py               # Marketplace → Lakebase facilities
python load_nfhs.py                      # NFHS-5 → Lakebase nfhs_state (demand overlay)
python extract.py 2500                   # score a representative sample

# deploy as a Databricks App
./scripts/deploy_databricks.sh
```

## Data

Virtue Foundation Dataset (DAIS 2026) `facilities` (10,088 rows), plus the India Post PIN
directory and NFHS‑5 district health indicators — all via Databricks Marketplace under the
Government Open Data License (India). Evidence fields are treated as **claims to verify**, not truth.

## Honest notes

- Trust signals are precomputed on a **representative sample** during the event; the full 10k
  is the same `extract.py` run.
- The **NFHS‑5 demand overlay is built**: each state carries a health‑burden need index, and
  the headline ranks **high‑risk shortfalls = burden × thin trusted supply** (a *rate* over
  evaluated facilities, so it's robust to sample size). At the **state** level there are no
  absolute deserts — every large state has *some* trusted supply — so we rank by thinness‑under‑
  burden rather than pretend a zero. **District‑level** gaps (where true deserts live) are next.
- Built live during the hackathon — see the commit history.
