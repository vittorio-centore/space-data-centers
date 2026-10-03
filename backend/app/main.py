"""Space Data Centers — FastAPI backend."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.assistant.service import AssistantService
from app.sim.world import SimWorld

app = FastAPI(title="Space Data Centers", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

world = SimWorld()
assistant = AssistantService()


class JobSubmit(BaseModel):
    input_bytes: int = 5_000_000
    output_bytes: int = 1_000_000
    work: float = 200.0
    deadline_at: Optional[float] = None
    source_id: str = "gs-ashburn"
    destination_id: str = "gs-ashburn"
    preset: Optional[str] = None


class SettingsPatch(BaseModel):
    sim_step_s: Optional[float] = None
    plan_horizon_s: Optional[float] = None
    speed: Optional[float] = None


class DisruptBody(BaseModel):
    down: bool = True
    bandwidth_factor: Optional[float] = None
    until: Optional[float] = None


@app.get("/health")
def health():
    return {"ok": True, "t": world.settings.t}


@app.get("/topology")
def topology():
    return {
        "nodes": [n.model_dump() for n in world.nodes],
        "ground_stations": [s.model_dump() for s in world.stations],
        "links": [L.model_dump() for L in world.links],
        "reality": {
            "ephemeris": "real_tle_sgp4",
            "contacts": "computed_from_real_geometry_plus_rules",
            "compute": "simulated",
            "bandwidth_pricing": "simulated",
            "ground_stations": "configured",
        },
    }


@app.get("/orbital-records")
def orbital_records():
    return [
        {
            "id": r.id,
            "name": r.name,
            "norad_id": r.norad_id,
            "source": r.source,
            "epoch": r.epoch,
            "reality": r.reality,
        }
        for r in world.records
    ]


@app.get("/nodes/{node_id}/track")
def node_track(node_id: str, duration: float = 5400.0, step: float = 45.0):
    """Sample ground-track LLA for orbit visualization (derived from real SGP4)."""
    node = world.node_by_id.get(node_id)
    if not node or not node.orbital_record_id:
        raise HTTPException(404, "orbital node not found")
    t0 = world.settings.t
    pts = world.orbit.ground_track(node.orbital_record_id, t0, duration_s=duration, step_s=step)
    return {"node_id": node_id, "t0": t0, "points": pts}


@app.get("/settings")
def get_settings():
    return world.settings.model_dump()


@app.patch("/settings")
async def patch_settings(body: SettingsPatch):
    if body.sim_step_s is not None:
        world.settings.sim_step_s = float(body.sim_step_s)
    if body.plan_horizon_s is not None:
        world.settings.plan_horizon_s = float(body.plan_horizon_s)
    if body.speed is not None:
        world.settings.speed = float(body.speed)
    await world.emit("metric", {"settings": world.settings.model_dump()})
    return world.settings.model_dump()


@app.post("/sim/play")
async def sim_play():
    await world.play()
    return {"playing": True, "t": world.settings.t}


@app.post("/sim/pause")
async def sim_pause():
    await world.pause()
    return {"playing": False, "t": world.settings.t}


@app.post("/sim/step")
async def sim_step():
    await world.step()
    return {"t": world.settings.t}


@app.post("/sim/reset")
async def sim_reset():
    await world.reset()
    return {"t": world.settings.t}


class SeekBody(BaseModel):
    t: float


@app.post("/sim/seek")
async def sim_seek(body: SeekBody):
    await world.seek(body.t)
    return {"t": world.settings.t}


@app.post("/presets/thesis/{case}")
async def run_thesis(case: str):
    if case not in ("a", "b", "case_a", "case_b", "case_a_cheap_loses", "case_b_cheap_wins"):
        raise HTTPException(400, "case must be a or b")
    return await world.submit_thesis(case)


@app.post("/jobs")
async def submit_job(body: JobSubmit):
    result = await world.submit_job(body.model_dump())
    if result.get("error") and result.get("plan") is None:
        # Still return 200 with failed job for demo UX; include error
        return result
    return result


@app.get("/jobs")
def list_jobs():
    return [j.model_dump() for j in world.jobs.values()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = world.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    plan = world.plans.get(job.plan_id or "")
    return {"job": job.model_dump(), "plan": plan.model_dump() if plan else None}


@app.get("/jobs/{job_id}/plan")
def get_plan(job_id: str):
    job = world.jobs.get(job_id)
    if not job or not job.plan_id:
        raise HTTPException(404, "plan not found")
    plan = world.plans.get(job.plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    return plan.model_dump()


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    if job_id not in world.jobs:
        raise HTTPException(404, "job not found")
    job = await world.cancel_job(job_id)
    return job.model_dump()


@app.post("/jobs/{job_id}/replan")
async def replan_job(job_id: str):
    if job_id not in world.jobs:
        raise HTTPException(404, "job not found")
    return await world.try_replan(job_id)


@app.get("/transfers")
def list_transfers():
    return [t.model_dump() for t in world.transfers.values()]


@app.get("/events")
def list_events(limit: int = 200):
    return [e.model_dump() for e in world.events[-limit:]]


@app.get("/workers")
def list_workers():
    return [w.model_dump() for w in world.workers.values()]


@app.post("/workers/{worker_id}/complete")
async def worker_complete(worker_id: str, body: dict[str, Any]):
    job_id = body.get("job_id")
    if not job_id or job_id not in world.jobs:
        raise HTTPException(404, "job not found")
    world.jobs[job_id].worker_done = True
    await world.emit("worker_complete", {"job_id": job_id, "worker_id": worker_id})
    return {"ok": True}


@app.post("/workers/{worker_id}/fail")
async def worker_fail(worker_id: str, body: dict[str, Any]):
    job_id = body.get("job_id")
    if not job_id or job_id not in world.jobs:
        raise HTTPException(404, "job not found")
    world.jobs[job_id].worker_error = body.get("error", "worker failed")
    await world.emit("worker_failed", {"job_id": job_id, "worker_id": worker_id})
    return {"ok": True}


@app.get("/metrics")
def metrics():
    return world.metrics()


@app.get("/snapshot")
def snapshot():
    return world.snapshot()


@app.get("/presets/thesis")
def thesis_presets():
    return world.thesis_presets()


@app.post("/links/{link_id}/disrupt")
async def disrupt_link(link_id: str, body: DisruptBody):
    if link_id not in world.link_by_id:
        raise HTTPException(404, "link not found")
    result = world.disrupt_link(
        link_id, down=body.down, bandwidth_factor=body.bandwidth_factor, until=body.until
    )
    await world.emit("link_disrupted", result)
    return result


@app.delete("/links/{link_id}/disrupt")
async def clear_disrupt(link_id: str):
    world.clear_disruption(link_id)
    await world.emit("link_disrupted", {"link_id": link_id, "disruption": None})
    return {"ok": True}


class AskBody(BaseModel):
    text: str
    source: str = "text"
    speak: bool = False


@app.get("/assistant/status")
def assistant_status():
    return assistant.status()


@app.post("/assistant/ask")
async def assistant_ask(body: AskBody):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    source = body.source if body.source in ("text", "voice") else "text"
    return await assistant.ask(world, text, source=source, speak=body.speak)


@app.post("/assistant/voice")
async def assistant_voice(file: UploadFile = File(...), speak: bool = True):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    return await assistant.voice(
        world,
        data,
        file.filename or "clip.webm",
        file.content_type or "application/octet-stream",
        speak=speak,
    )


@app.websocket("/ws")
async def websocket_events(ws: WebSocket):
    await ws.accept()
    q = world.subscribe()
    try:
        # send hello + snapshot summary
        await ws.send_json(
            {
                "id": "hello",
                "t": world.settings.t,
                "type": "hello",
                "payload": {"reality": "ephemeris real; bandwidth/compute simulated"},
            }
        )
        while True:
            ev = await q.get()
            await ws.send_json(ev.model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        world.unsubscribe(q)


def create_app() -> FastAPI:
    return app
