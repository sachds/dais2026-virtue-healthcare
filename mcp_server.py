#!/usr/bin/env python3
"""Trust Desk MCP — the Facility Trust Desk's Lakebase substrate exposed as MCP
tools, so an Omnigent agent can plan → retrieve → reason over evidence-cited
trust signals (and persist its decision) the same way the in-process Referral
Copilot does. The tool bodies live in app/agent_tools.py — ONE source of truth;
this file is just the MCP transport over them.

Mounted into an Omnigent agent via its config.yaml:

    tools:
      trust_desk:
        type: mcp
        command: /abs/path/commons/.venv/bin/python      # a venv with mcp + psycopg
        args: [/abs/path/trustdesk/mcp_server.py]
        env:
          LAKEBASE_URL: postgresql://commons_app:<pw>@<host>:5432/databricks_postgres?sslmode=require

Dual transport: stdio (default) for Omnigent's local runner; streamable-http to
host as a CUSTOM MCP SERVER on Databricks Apps (OAuth + UC governed).
"""
from __future__ import annotations

import os
import sys

# Make the `app` package importable however this file is launched (Omnigent
# spawns it as a subprocess with an arbitrary cwd).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app import agent_tools  # noqa: E402

mcp = FastMCP("trust-desk")


@mcp.tool()
def find_facilities(capabilities: list[str], location: str = "", limit: int = 6) -> list:
    """Retrieve facilities with supporting evidence for the requested capabilities
    (icu|maternity|emergency|oncology|trauma|nicu) in a location, ranked by trust
    signal. Returns compact candidates, each with a cited evidence snippet."""
    return agent_tools.find_facilities(capabilities, location, limit)


@mcp.tool()
def facility_evidence(facility_id: str) -> dict:
    """Full per-capability trust signals + exact cited evidence for one facility
    (applies analyst overrides). Use to scrutinize a candidate before recommending."""
    return agent_tools.facility_evidence(facility_id)


@mcp.tool()
def state_demand(state: str) -> dict:
    """NFHS-5 health-burden context for a state (need index + indicators), to weigh
    how underserved the surrounding population is — not just whether a facility exists."""
    return agent_tools.state_demand(state)


@mcp.tool()
def record_decision(facility_id: str, body: str, capability: str = "") -> dict:
    """Persist a referral decision/note to Lakebase (append-only reviews) as a
    durable, attributable action."""
    return agent_tools.record_decision(facility_id, body, capability or None)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http", "sse"):
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("PORT") or os.environ.get("DATABRICKS_APP_PORT") or 8000)
        mcp.run(transport="sse" if transport == "sse" else "streamable-http")
    else:
        mcp.run()  # stdio — for Omnigent's local runner
