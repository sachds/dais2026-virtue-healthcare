"""Facility Trust Desk — a Databricks App on Lakebase (Track 1).

Turns 10k messy Indian healthcare facility records into evidence-attached,
uncertainty-aware capability trust signals a non-technical planner can act on —
and persists their overrides / notes / shortlists.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db

HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="Facility Trust Desk")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/healthz")
async def healthz():
    return JSONResponse(await asyncio.to_thread(db.health))


@app.get("/api/overview")
async def overview():
    return JSONResponse(await asyncio.to_thread(db.overview))


@app.get("/api/desert")
async def desert():
    return JSONResponse(await asyncio.to_thread(db.desert_grid))


@app.get("/api/readiness")
async def readiness():
    return JSONResponse(await asyncio.to_thread(db.readiness))


@app.get("/api/services")
async def services():
    return JSONResponse(await asyncio.to_thread(db.services_overview))


@app.get("/api/districts")
async def districts():
    return JSONResponse(await asyncio.to_thread(db.district_rollup))


@app.get("/api/desertmap")
async def desertmap(capability: str = "any"):
    return JSONResponse(await asyncio.to_thread(db.district_supply, capability))


@app.get("/api/states")
async def states():
    return JSONResponse({"states": await asyncio.to_thread(db.states)})


@app.get("/api/facilities")
async def facilities(q: str = "", state: str = "", capability: str = "",
                     signal: str = "", limit: int = 40):
    rows = await asyncio.to_thread(db.list_facilities, q, state, capability, signal, limit)
    return JSONResponse({"facilities": rows})


@app.get("/api/facility/{fid}")
async def facility(fid: str):
    d = await asyncio.to_thread(db.get_facility, fid)
    return JSONResponse(d, status_code=200) if d else JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/review")
async def review(payload: dict):
    if not payload.get("action"):
        return JSONResponse({"error": "action required"}, status_code=400)
    row = await asyncio.to_thread(
        db.record_review, payload.get("action"), payload.get("facility_id"),
        payload.get("capability"), payload.get("new_signal"), payload.get("body"),
        payload.get("shortlist"), payload.get("user_id", "planner"))
    return JSONResponse({"ok": True, "review": row})


@app.get("/api/shortlist")
async def get_shortlist(name: str = "default"):
    return JSONResponse({"shortlist": await asyncio.to_thread(db.shortlist, name)})


@app.post("/api/copilot")
async def copilot(payload: dict):
    q = (payload.get("query") or "").strip()
    if not q:
        return JSONResponse({"error": "query required"}, status_code=400)
    from app import copilot as cp
    return JSONResponse(await asyncio.to_thread(cp.run, q))


@app.post("/api/publichealth/immunization")
async def ph_immunization(payload: dict):
    from app import publichealth as ph
    return JSONResponse(await asyncio.to_thread(ph.immunization_campaign, payload.get("region", "")))


@app.post("/api/publichealth/outbreak")
async def ph_outbreak(payload: dict):
    region = (payload.get("region") or "").strip()
    if not region:
        return JSONResponse({"error": "region required"}, status_code=400)
    from app import publichealth as ph
    return JSONResponse(await asyncio.to_thread(ph.outbreak_protocol, region, payload.get("disease", "")))
