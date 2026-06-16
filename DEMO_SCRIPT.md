# Care Compass — 3‑minute demo script (full scale ladder)

One protagonist (a Virtue Foundation coordinator placing the next ICU resource) walks the **whole
scale ladder** — Population → Network → Facility → Patient → Foundation — using the app's own
cross‑scale handoffs, so it reads as **one connected workbench**, not seven tabs. Hits all four
criteria; the Care Network chokepoint is the centerpiece.

Voiceover ≈ 380 words. Every tab appears. **Pre‑load the agentic panes** (see notes) so you narrate
over results, not spinners.

---

### 1 · Overview — hook + thesis  ·  [0:00–0:18]
**DO:** Start on **Overview**. Cursor across the four scale cards.
**SAY:** "Virtue Foundation gave us ten thousand Indian healthcare facility records — and the catch
is, they're *claims, not truth*. So we built **Care Compass**: one trust substrate — every claim
graded against its cited evidence — with a decision tool at *every scale*. It's a Databricks App:
Marketplace data, trust signals extracted with Foundation Model APIs into Lakebase."

### 2 · Population — Gap map + Public Health  ·  [0:18–0:44]
**DO:** Click **🗺 Gap map** (opens on ICU). Point at a **red** bubble; click the **MATERNITY** chip
so the deserts change, then back to **ICU**. Then click **⚕ Public Health** and let the agent cards +
the NFHS baselines strip show for ~2s.
**SAY:** "Population scale — where's the danger? Red is a *care desert*: the district has facilities,
but none with trusted evidence for — here — ICU. Switch to maternity and a different map lights up.
At this scale we also run population agents — immunization campaigns, outbreak isolation,
disease‑burden escalation. But let's chase that ICU gap into the network."

### 3 · Network — THE centerpiece  ·  [0:44–1:24]
**DO:** Click **⇄ Care Network** → in the **"in"** dropdown pick **Madhya Pradesh** → **⇄ Map the
network**. (Notice the **Focus bar** now reads 🗺 Madhya Pradesh · ICU.) Point at the red **Systemic
risk** box, then the **#1 chokepoint**.
**SAY:** "Network scale — what no single tool can see. We coordinate a referral agent from *every*
facility and aggregate it: 282 facilities funnel their ICU referrals onto nineteen hospitals. And the
number‑one chokepoint — that 31 depend on — has only *partial* evidence. The skeptic pulled its
actual source text: a *stroke‑monitoring unit*. Not an ICU. The coordinated view flags it as a single
point of failure."

### 4 · Network → action  ·  [1:24–1:42]
**DO:** In the **"Act on this →"** row click **⊕ Add capacity**.
**SAY:** "So where do we add capacity? The optimizer recommends a 120‑bed hospital in Chhatarpur —
five isolated facilities brought within reach. The gap becomes a decision."

### 5 · Facility — verify it (handoff)  ·  [1:42–2:04]
**DO:** Scroll to the chokepoint list, click the **#1 row (A. K. Hospital — *trust‑check*)**. It opens
in the **Trust Desk**. Point at the **ICU** card: **partial** badge + the **cited evidence** snippet +
the **override** buttons.
**SAY:** "Click any chokepoint to trust‑check it. Here's the proof — its ICU signal is *partial*, and
here's the exact cited text: a brain stroke monitoring unit. Claims to verify, not facts. A
coordinator can override it, and it saves to Lakebase."

### 6 · Patient — refer (handoff)  ·  [2:04–2:30]
**DO:** In the facility detail, click **✦ Refer a patient from here** → the **Referral Copilot** opens
with this facility pre‑filled. Type **`needs ICU`** → Ask. (Pre‑load this; narrate over it.) Point at
the governed shortlist + the **referral note**.
**SAY:** "And on the ground, a provider refers a patient — a *governed* mesh that plans, challenges
each claim, blocks the ones that don't hold up, and writes a referral note to hand over. Evidence all
the way down to the patient."

### 7 · Foundation — Data Readiness  ·  [2:30–2:48]
**DO:** Click **✓ Data Readiness**. Gesture at the field‑coverage bars and the **review queue** (the
over‑claims).
**SAY:** "And it all sits on a data‑readiness foundation: we profile what's sparse, what's weak, and
queue the over‑claims that most need a human. We're honest about the data."

### 8 · Close  ·  [2:48–3:00]
**DO:** Click **⌂ Overview** (or open **✦ Ask AI** and let it sit).
**SAY:** "No patient records, no outcomes data — and we say so. But from ten thousand messy claims,
Care Compass turns supply into trusted decisions at every scale — and you can ask any of it, on any
page. Live, on Databricks."

---

## Production notes
- **Record on the deployed app** (service principal → no token expiry / no fallback text).
- **Pre‑load the slow panes** in a warm‑up pass, then either narrate over the loading‑step indicators
  or trim the spinner in editing. Agentic steps and their ~latency:
  - Care Network (step 3) ~8s · Add capacity (step 4) ~6s · Referral Copilot (step 6) ~10–12s.
  - Public Health *landing* (step 2) and Data Readiness (step 7) are fast — no agent runs.
- **Use Madhya Pradesh** in the Care Network (282 → 19, A. K. Hospital). The chokepoint click in
  step 5 reliably opens A. K. Hospital; "Refer a patient from here" in step 6 reliably opens the
  Copilot pre‑filled — those two handoffs are the connective tissue, lean on them.
- **Stable facts** (LLM prose varies, these don't): MP ICU **282→19** · **A. K. Hospital · 31 ·
  partial · "Brain Stroke Monitoring Unit"** · siting **Christian Hospital, Chhatarpur · 120 beds · 5
  closer**.
- Keep the **Focus bar** visible (🗺 MP · ICU · 🏥 A. K. Hospital) — it sells "one workbench."
- Full‑screen, ~1320×900, bookmarks hidden.

## Click path (rehearse)
Overview → Gap map (ICU→Maternity→ICU) → Public Health (glance) → Care Network (pick **Madhya
Pradesh** → Map) → **⊕ Add capacity** → click **#1 chokepoint** (→ Trust Desk) → **✦ Refer a patient
from here** (→ Copilot, type `needs ICU`) → Data Readiness → Overview.

## If you fall behind (cut order)
Trim step 2's Public Health glance → step 4 siting → step 7 Data Readiness to one line. Never cut
3 (the centerpiece), 5 (verify), or 6 (the patient payoff).
