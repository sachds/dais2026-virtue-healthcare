# Demo runbook — ~4 minutes, five panes, one substrate

One Databricks App on Lakebase. The arc: **honest data → trustworthy individual decisions →
community decisions**, with agents that show their work. The top **tabs** are the spine.

> Live: `https://facility-trust-desk-5528334136090880.aws.databricksapps.com`
> Tight on time? Do **0 → 1 → 3 → 4** (hook, map, copilot, public health) and skip 2 + 5.

## The flow

### 0 · Hook *(20s)*
> "A health planner has 10,000 facility records full of noisy claims, and almost no patient
> data. Acting on a false 'ICU: yes' is dangerous. We score every claim from the facility's
> own words, map where care actually is, and build agents that show their work — for one
> patient, and for a whole community."

### 1 · Where are the deserts? — **Gap map** *(45s)*
- Land on the **map view**. Switch the selector to **ICU deserts**.
> "Every dot is a district at its real coordinates — they self‑form India. Green is trusted ICU
> supply, **red is a confirmed gap** — a district we evaluated where *nothing* is trusted. State
> level hides these; district level shows **13 real ICU deserts**, like Anand."
- Flip to **Table**: the state heatmap + the **Need** column.
> "And we weight by demand — NFHS‑5 health burden. The headline isn't 'empty', it's the
> **dangerous shortfall**: burden × thin trusted supply. We never call a data hole a desert."

### 2 · Why believe a claim? — **Trust Desk** *(40s)*
- Search a clinic, open it. Show a capability card.
> "Every claim is scored from the **exact source text quoted** — and cross‑checked by
> **cardinality**: this clinic is scored *Strong ICU* from its bed blurb, but it has **0 ICU
> specialists** on record, so we flag it — *claim not corroborated*. Disagree? Override it; it
> saves to Lakebase. The data is claims to verify, not truth."

### 3 · Where should this patient go? — **Referral Copilot** *(50s)*
- Ask: **"cancer care near Ranchi"**.
> "A **governed mesh**, not one model call: it plans, retrieves, and a **skeptic challenges every
> claim**. Then **code policy** gates it — it recommends only ✓ vetted facilities and **✗ blocks**
> what it can't stand behind, like a hospital whose only 'oncology' is *urologic oncology*."
- Ask: **"diabetic patient near Pune, 3 visits this month"**.
> "For a chronic condition it builds a **care team** — a diabetic needs an **eye exam** for
> retinopathy and a **dentist**, so it brings both on, **nearest by distance**. And 3 visits this
> month trips an **escalation**: stop managing in a clinic, go to a specialist + hospital."
- *(aside)* The same loop runs under **real Omnigent** — `./scripts/run_referral_agent.sh`.

### 4 · What's good for the community? — **Public Health** *(50s)*
- **Immunization campaign** → *Plan campaign*.
> "Now population scale. The agent finds the **under‑vaccinated districts that have local supply**
> — Banas Kantha, 43% — and drafts a campaign over the real facilities and physicians."
- **Disease burden** → click **⚑ escalate** on Dohad (anaemia × stunting).
> "It benchmarks prevalence by geography, links **anaemia and stunting**, and **makes the problem
> visible** — an agent drafts the escalation to **WHO, UNICEF, the state health department, NGOs**,
> grounded in Dohad's real 87% anaemia. For the good of the community."
- *(aside)* **Outbreak response** mode plans isolation from a district's real bed capacity.

### 5 · The honesty layer — **Data Readiness** *(25s)*
> "And we're honest about the data: a **classification** of every provider into service lines with
> **beds per line**, the rule that **facilities must have beds and providers a specialty** (3,253
> hospitals miss a bed count), and the **over‑claim queue** — a dental spa claiming oncology,
> surfaced for review."

### 6 · Close *(20s)*
> "One Lakebase substrate, five lenses, and a fleet of **governed agents** that cite their
> evidence and show what they refused — for the patient *and* the community. Marketplace →
> Lakebase → evidence extraction → a Databricks App, runnable under Omnigent. And we tell you
> exactly what the data can't say."

## Fallbacks
- **Agent slow/unavailable** → every agent degrades to a deterministic grounded output; don't wait on a model on stage.
- **A map looks mostly grey/green** → that's honest (sparse scoring at district level); switch capability, or note gaps sharpen as coverage grows.
- **Data‑wall questions** (patients, outbreak detection, insurance networks) → say it plainly: not in this data; wired in the moment a feed is connected. That honesty *is* the pitch.
