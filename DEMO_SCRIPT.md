# Care Compass — 3‑minute demo script (action‑by‑action)

Each step = **DO** (exact click) + **SAY** (exact words). ~3:00 total.

### Before you hit record
- Open the **deployed** app full‑screen on the **Overview** page (deployed = service principal =
  no token expiry, no fallback text). Hide the bookmarks bar; ~1280–1440px wide.
- **Warm it up once:** in a second tab, go to Care Network → pick **Madhya Pradesh** → Map the
  network, and run **Add capacity** once. (First run caches nothing, but it confirms it's healthy and
  primes your timing.)
- The agent steps take ~6–10s. **Narrate over the loading steps** (they animate the pipeline) or trim
  the spinner in editing.

---

### 1 · Overview — the hook  ·  [0:00–0:18]
**DO:** Stay on the Overview page. Don't click yet.
**SAY:** "Virtue Foundation gave us ten thousand Indian healthcare facility records — and the catch
is, they're *claims, not truth*. A clinic can list an ICU with nothing behind it. So if you're
deciding where to send a critical patient, or where to put your next ICU — who do you trust? That's
Care Compass."

### 2 · Overview — the thesis  ·  [0:18–0:33]
**DO:** Move the cursor across the four scale cards (Population → Network → Facility → Patient).
**SAY:** "One trust substrate — every claim graded against its cited evidence — with a decision tool
at *every scale*, from one patient to a whole population. It's a Databricks App: data from
Marketplace, trust signals extracted with Foundation Model APIs into Lakebase."

### 3 · Gap map — population scale  ·  [0:33–0:56]
**DO:** Click **🗺 Gap map**. It opens on **ICU** — point at a **red** bubble. Then click the
**MATERNITY** chip in "Show deserts for:" so the deserts visibly change; click back to **ICU**.
**SAY:** "Population scale — where's the danger? Each bubble is a district, and **red is a care
desert**: facilities are there, but *none with trusted evidence* for — here — ICU. Thirteen of them.
Switch the filter to maternity and a *different* map of deserts lights up. And the **Table** ranks
these by NFHS‑5 health burden — so you see where the gap is most *dangerous*, not just where it is."

### 4 · Care Network — run it  ·  [0:52–1:06] (then ~8s load)
**DO:** Click **⇄ Care Network** in the sidebar → in the **"in"** dropdown choose **Madhya Pradesh**
→ click **⇄ Map the network**.
**SAY (over the loading steps):** "Now the network scale — and this is what no single tool can see. We
coordinate a referral agent from *every* facility in the state and aggregate it. Watch: it routes
each facility to its nearest trusted ICU, then a skeptic checks the result."

### 5 · Care Network — THE moment  ·  [1:06–1:34]
**DO:** When it renders, point at the red **"⚠ Systemic risk"** box, then the **#1 chokepoint** in the
list below.
**SAY:** "Two hundred eighty‑two facilities funnel their ICU referrals onto nineteen hospitals. And
the number‑one chokepoint — that *thirty‑one* facilities depend on — has only *partial* evidence. The
skeptic pulled its actual source text: a *stroke‑monitoring unit*. Not an ICU. One referral would
route there blindly; the coordinated view flags it as a single point of failure."

### 6 · Trust Desk — verify it (facility scale)  ·  [1:34–1:58]
**DO:** Click the **#1 chokepoint row** ("A. K. Hospital" — it reads *trust‑check this destination*).
It opens in the Trust Desk. Point at the **ICU** capability card: the **partial** badge, the
**Cited evidence** snippet, and the **Analyst override** buttons. (Glance at the **Focus bar** now
showing 🗺 Madhya Pradesh · ICU · 🏥 A. K. Hospital.)
**SAY:** "Click it to trust‑check. Here's the proof — its ICU signal is *partial*, and here's the
exact cited text it's based on: a brain stroke monitoring unit. Claims to verify, not facts. If you
disagree you override it right here, and it saves to Lakebase."

### 7 · Care Network — turn it into a plan  ·  [1:58–2:24] (then ~6s load)
**DO:** Click **⇄ Care Network** in the sidebar (your result is still there) → in the **"Act on
this →"** row click **⊕ Add capacity**.
**SAY (over the load):** "So if that node is unreliable — where do we add capacity? The optimizer
simulates resourcing each existing hospital, and recommends a 120‑bed hospital in Chhatarpur — it
brings five isolated facilities within reach. That's the whole point: turn the gap into a decision."

### 8 · Ask AI — it's everywhere  ·  [2:24–2:42]  *(cut this beat first if you're over time)*
**DO:** Click **✦ Ask AI** (top right). Type **`where should I add capacity in Bihar?`** → Enter.
**SAY:** "And an assistant works on *every* page — plain language, the same governed tools, and it
shows its work."

### 9 · Close  ·  [2:42–3:00]
**DO:** Close the panel; click **⌂ Overview** in the sidebar.
**SAY:** "We're honest about the limits — no patient records, no outcomes data, and we *say so*. But
from ten thousand messy claims, Care Compass turns supply into trusted decisions at every scale.
Live, on Databricks."

---

### Stable facts (narrate to these — the LLM prose varies, these don't)
- Madhya Pradesh ICU: **282 → 19**, chokepoint **A. K. Hospital** · **31 referrals** · **partial** ·
  cited *"Brain Stroke Monitoring Unit."*
- Siting top pick: **Christian Hospital, Chhatarpur · 120 beds · 5 facilities closer.**

### If you must hit 2:00
Keep **1 → 4 → 5 → 6 → 9** (hook → run the network → the chokepoint → verify it → close). That alone
covers product judgment, evidence, uncertainty, and ambition.
