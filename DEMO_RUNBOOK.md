# Demo runbook — 3 minutes, four lenses

One app, four tracks, one trust‑signal substrate in Lakebase. Drive it live; the
nav buttons (**Gap map**, **Data readiness**) and the **Copilot** bar are the spine.

> Live: `https://facility-trust-desk-5528334136090880.aws.databricksapps.com`

## The 3‑minute flow

### 0 · Hook *(15s)*
> "A health planner has 10,000 facility records full of noisy claims. Acting on a
> false 'ICU: yes' is dangerous. We score every claim from the facility's own
> words — and show our work."

### 1 · Where are the gaps? — **Track 2, the landing** *(40s)*
- Show the **Gap map**: states × capabilities, green = trusted supply, **red = confirmed gap**, grey = too little data.
> "The key move: we separate a *real* gap — many facilities evaluated, none trusted — from a
> *data‑poor* region we simply haven't covered. We never call a data hole a desert."

### 2 · Why do we believe a gap? — **Track 1, drill‑down** *(40s)*
- Click a cell → the facilities → click one → the **trust cards**.
> "Each capability is scored with the **exact source text quoted** — 'Has 5 ICU beds' — plus a
> confidence. Disagree? Override it; it's saved to Lakebase. The data is claims to verify, not truth."

### 3 · Where should this patient go? — **Track 3, the live agent** *(40s)*
- In the Copilot bar: **"emergency and ICU near Patna"**.
> "A live agent: it plans the need, **retrieves from Lakebase**, reasons over the trust signals,
> and returns an **evidence‑cited shortlist** — and flags a dental clinic's '24/7 emergency' as not
> a real ER. ~9 seconds, on Claude Haiku."

### 4 · What needs fixing first? — **Track 4, data readiness** *(30s)*
- Hit **Data readiness**: the coverage profile + the **over‑claim queue**.
> "A dental spa claiming *strong oncology* — surfaced automatically for human review. Plus field
> sparseness (capacity 25%, doctors 36%) so planners know the data's limits."

### 5 · Close *(15s)*
> "We didn't pick a track — we built the planning system. Marketplace → Lakebase → GPT‑5.5
> evidence extraction → a Databricks App, with a live Claude agent on top. Every number cites its source."

## Fallbacks
- **Copilot slow/unavailable** → it degrades to a deterministic evidence‑ranked shortlist; don't wait on a model on stage.
- **A cell looks all‑green** → that's honest at the state level; drill in, or note gaps sharpen as coverage grows.
- Never present a weak signal as fact — the UI already won't.
