# Demo runbook — 3 minutes, four lenses

One app, four tracks, one trust‑signal substrate in Lakebase. Drive it live; the
nav buttons (**Gap map**, **Data readiness**) and the **Copilot** bar are the spine.

> Live: `https://facility-trust-desk-5528334136090880.aws.databricksapps.com`

## The 3‑minute flow

### 0 · Hook *(15s)*
> "A health planner has 10,000 facility records full of noisy claims. Acting on a
> false 'ICU: yes' is dangerous. We score every claim from the facility's own
> words — and show our work."

### 1 · Where is the dangerous shortfall? — **Track 2, the landing** *(45s)*
- Show the **Gap map**: states × capabilities. Cells shade **thin → robust** by how many evaluated
  facilities actually show trusted evidence; the **Need** column is **NFHS‑5 health burden**.
> "At the state level there's no absolute desert — every big state has *some* trusted supply. So we
> overlay demand: the headline is **highest‑risk shortfalls = health burden × thin trusted supply**.
> For example ICU in Jharkhand — only ~a quarter of evaluated facilities show trusted evidence, in a
> high‑burden, low‑insurance state. And we still separate that from a *data‑poor* region we simply
> haven't covered — we never call a data hole a desert."

### 2 · Why do we believe a gap? — **Track 1, drill‑down** *(40s)*
- Click a cell → the facilities → click one → the **trust cards**.
> "Each capability is scored with the **exact source text quoted** — 'Has 5 ICU beds' — plus a
> confidence. Disagree? Override it; it's saved to Lakebase. The data is claims to verify, not truth."

### 3 · Where should this patient go? — **Track 3, the governed agent** *(45s)*
- In the Copilot bar: **"cancer care near Ranchi"**.
> "Not one model call — a **governed mesh that shows its work**: it plans, retrieves from Lakebase,
> scrutinizes each record, and a **skeptic adversarially challenges every claim**. Then a **code
> policy gates the output**: it recommends only ✓ *vetted* facilities, ⚠ *flags* over‑claims (a
> day‑care clinic's outpatient‑only chemo), and ✗ **blocks** what it can't stand behind — a hospital
> whose only 'oncology' is *urologic oncology*. You see the trace, the verdicts, and what it refused."
- Point at the trace + the **"Not recommended — blocked by policy"** row. *The same loop runs under
  **real Omnigent*** (`./scripts/run_referral_agent.sh`) over the trust‑desk MCP — composition + control
  on the same Lakebase substrate.

### 4 · What needs fixing first? — **Track 4, data readiness** *(30s)*
- Hit **Data readiness**: the coverage profile + the **over‑claim queue**.
> "A dental spa claiming *strong oncology* — surfaced automatically for human review. Plus field
> sparseness (capacity 25%, doctors 36%) so planners know the data's limits."

### 5 · Close *(15s)*
> "We didn't pick a track — we built the planning system. Marketplace → Lakebase → GPT‑5.5
> evidence extraction → a Databricks App, with a **governed multi‑agent referral mesh** on top —
> the same loop runnable under **Omnigent** over an MCP of the trust substrate. Every number cites
> its source, and the agent shows what it refused to recommend."

## Fallbacks
- **Copilot slow/unavailable** → it degrades to a deterministic evidence‑ranked shortlist; don't wait on a model on stage.
- **A cell looks all‑green** → that's honest at the state level; drill in, or note gaps sharpen as coverage grows.
- Never present a weak signal as fact — the UI already won't.
