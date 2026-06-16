# Referral agent — under real Omnigent

The same governed referral loop the app runs in-process (`app/copilot.py`), here
as an **Omnigent** agent that mounts the Facility Trust Desk's Lakebase as MCP
tools (`mcp_server.py` over `app/agent_tools.py`) and is gated by the same trust
rules. This is the authentic incorporation: Omnigent **composes** the loop,
**controls** it (the agent can't recommend past the governance), and the MCP is
the shared substrate the app and the harness both read.

## Run it

```bash
# needs trustdesk/.env (LAKEBASE_URL) + an Omnigent install at hackathon/.omni-venv
# (see commons/scripts/run_omnigent.sh) and a logged-in claude CLI / model credential.
./scripts/run_referral_agent.sh "cancer care near Ranchi"
```

The script renders `agents/referral/config.yaml` (which ships with `__LAKEBASE_URL__`
placeholders — the password never lives in git) into a temp bundle dir with the
concrete Lakebase URL, then `omnigent run`s it headless.

## What it does (verified run — "cancer care near Ranchi")

The agent planned → `find_facilities` → `facility_evidence` (scrutinize) →
adversarial challenge → governance → `state_demand`, then answered:

> Two full-service hospitals have genuinely strong, specific oncology evidence:
> **Raj Hospital & Research Centre** (*"surgical oncology, medical oncology,
> radiation oncology, and nuclear medicine"*) and **Bhagwan Mahavir Medica**
> (*"100-bed oncology department … comprehensive oncology services"*). **RJSP
> Cancer Hospital** is a dedicated cancer center but shows **no ICU and only weak
> emergency** — pair it with a hospital for acute support. Jharkhand is moderately
> underserved (NFHS need index 0.43).
>
> **What I refused to recommend — Hill View Hospital:** its only oncology citation
> is *"urologic oncology"* inside a urology service line. That establishes urology,
> not general cancer treatment — a mismatch, so I won't present it as an oncology
> provider (it does have credible maternity and trauma evidence for other needs).

It flagged a blanket-claim hospital and an outpatient-only day-care clinic with
mandatory cautions, and blocked the mismatched claim — the same outcomes the
in-process mesh produces, here under the real harness.
