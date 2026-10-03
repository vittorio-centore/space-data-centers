"""Shared route table registered on / and /api/v1."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.api.schemas import (
    DisruptBody,
    EvaluationBody,
    JobBatchSubmit,
    JobSubmit,
    OutageBody,
    ScenarioBody,
    SeekBody,
    SettingsPatch,
)
from app.auth import authorize_websocket
from app.eval.runner import run_evaluation
from app.scenarios.catalog import list_scenarios


def build_router(get_world, *, include_in_schema: bool = True) -> APIRouter:
    router = APIRouter(include_in_schema=include_in_schema)

    @router.get("/health")
    def health():
        w = get_world()
        return {"ok": True, "t": w.settings.t, "scenario": w.settings.scenario_id}

    @router.get("/ready")
    def ready():
        body = get_world().ready()
        if not body.get("ok"):
            raise HTTPException(503, body.get("error") or "not ready")
        return body

    @router.get("/topology")
    def topology():
        w = get_world()
        return {
            "nodes": [n.model_dump() for n in w.nodes],
            "ground_stations": [s.model_dump() for s in w.stations],
            "links": [L.model_dump() for L in w.links],
            "scenario": w.settings.scenario_id,
            "reality": {
                "ephemeris": "real_tle_sgp4",
                "contacts": "computed_from_real_geometry_plus_rules",
                "compute": "simulated",
                "bandwidth_pricing": "simulated",
                "ground_stations": "configured",
                "power_thermal": "labelled_assumption_not_telemetry",
            },
        }

    @router.get("/contacts")
    def contacts(horizon_s: Optional[float] = None):
        """Full-horizon visibility matrix for the inspector (same grid as the planner)."""
        return get_world().contacts_inspector(horizon_s)

    @router.get("/orbital-records")
    def orbital_records():
        w = get_world()
        return [
            {
                "id": r.id,
                "name": r.name,
                "norad_id": r.norad_id,
                "source": r.source,
                "epoch": r.epoch,
                "reality": r.reality,
            }
            for r in w.records
        ]

    @router.get("/nodes/{node_id}/track")
    def node_track(node_id: str, duration: float = 5400.0, step: float = 45.0):
        w = get_world()
        node = w.node_by_id.get(node_id)
        if not node or not node.orbital_record_id:
            raise HTTPException(404, "orbital node not found")
        t0 = w.settings.t
        pts = w.orbit.ground_track(node.orbital_record_id, t0, duration_s=duration, step_s=step)
        return {"node_id": node_id, "t0": t0, "points": pts}

    @router.get("/nodes/{node_id}/power")
    def node_power(node_id: str):
        w = get_world()
        node = w.node_by_id.get(node_id)
        if not node:
            raise HTTPException(404, "node not found")
        return {"node_id": node_id, "power_thermal": node.power_thermal}

    @router.post("/nodes/{node_id}/outage")
    async def node_outage(node_id: str, body: OutageBody):
        w = get_world()
        if node_id not in w.node_by_id:
            raise HTTPException(404, "node not found")
        result = w.set_outage(node_id, down=body.down, until=body.until, reason=body.reason)
        await w.emit("node_outage", result)
        return result

    @router.get("/settings")
    def get_settings():
        return get_world().settings.model_dump()

    @router.patch("/settings")
    async def patch_settings(body: SettingsPatch):
        w = get_world()
        if body.sim_step_s is not None:
            w.settings.sim_step_s = float(body.sim_step_s)
            w.orbit.set_cache_step(w.settings.sim_step_s)
            w.visibility.set_step(w.settings.sim_step_s)
        if body.plan_horizon_s is not None:
            w.settings.plan_horizon_s = float(body.plan_horizon_s)
        if body.speed is not None:
            w.settings.speed = float(body.speed)
        await w.emit("metric", {"settings": w.settings.model_dump()})
        return w.settings.model_dump()

    @router.post("/sim/play")
    async def sim_play():
        w = get_world()
        await w.play()
        return {"playing": True, "t": w.settings.t}

    @router.post("/sim/pause")
    async def sim_pause():
        w = get_world()
        await w.pause()
        return {"playing": False, "t": w.settings.t}

    @router.post("/sim/step")
    async def sim_step():
        w = get_world()
        await w.step()
        return {"t": w.settings.t}

    @router.post("/sim/reset")
    async def sim_reset():
        w = get_world()
        await w.reset()
        return {"t": w.settings.t}

    @router.post("/sim/seek")
    async def sim_seek(body: SeekBody):
        w = get_world()
        await w.seek(body.t)
        return {"t": w.settings.t}

    @router.get("/scenarios")
    def scenarios():
        return list_scenarios()

    @router.post("/scenarios")
    async def load_scenario(body: ScenarioBody):
        return await get_world().load_scenario(body.id)

    @router.post("/presets/thesis/{case}")
    async def run_thesis(case: str):
        if case not in ("a", "b", "case_a", "case_b", "case_a_cheap_loses", "case_b_cheap_wins"):
            raise HTTPException(400, "case must be a or b")
        return await get_world().submit_thesis(case)

    @router.get("/presets/thesis")
    def thesis_presets():
        return get_world().thesis_presets()

    @router.post("/jobs")
    async def submit_job(body: JobSubmit):
        return await get_world().submit_job(body.model_dump())

    @router.post("/jobs/batch")
    async def submit_batch(body: JobBatchSubmit):
        return await get_world().submit_batch([j.model_dump() for j in body.jobs], policy=body.policy)

    @router.get("/jobs")
    def list_jobs():
        return [j.model_dump() for j in get_world().jobs.values()]

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        w = get_world()
        job = w.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        plan = w.plans.get(job.plan_id or "")
        return {"job": job.model_dump(), "plan": plan.model_dump() if plan else None}

    @router.get("/jobs/{job_id}/plan")
    def get_plan(job_id: str):
        w = get_world()
        job = w.jobs.get(job_id)
        if not job or not job.plan_id:
            raise HTTPException(404, "plan not found")
        plan = w.plans.get(job.plan_id)
        if not plan:
            raise HTTPException(404, "plan not found")
        return plan.model_dump()

    @router.get("/jobs/{job_id}/plans")
    def plan_history(job_id: str):
        w = get_world()
        if job_id not in w.jobs:
            raise HTTPException(404, "job not found")
        hist = [p.model_dump() for p in w.plan_revisions if p.job_id == job_id]
        if w.store:
            hist = w.store.plan_history(job_id) or hist
        return hist

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        w = get_world()
        if job_id not in w.jobs:
            raise HTTPException(404, "job not found")
        job = await w.cancel_job(job_id)
        return job.model_dump()

    @router.post("/jobs/{job_id}/replan")
    async def replan_job(job_id: str):
        w = get_world()
        if job_id not in w.jobs:
            raise HTTPException(404, "job not found")
        return await w.try_replan(job_id)

    @router.get("/transfers")
    def list_transfers():
        return [t.model_dump() for t in get_world().transfers.values()]

    @router.get("/events")
    def list_events(limit: int = 200, since: int = Query(default=0, ge=0)):
        w = get_world()
        evs = w.events_since(since) if since else w.events
        return [e.model_dump() for e in evs[-limit:]]

    @router.get("/workers")
    def list_workers():
        return [w.model_dump() for w in get_world().workers.values()]

    @router.post("/workers/{worker_id}/complete")
    async def worker_complete(worker_id: str, body: dict[str, Any]):
        w = get_world()
        job_id = body.get("job_id")
        if not job_id or job_id not in w.jobs:
            raise HTTPException(404, "job not found")
        w.jobs[job_id].worker_done = True
        await w.emit("worker_complete", {"job_id": job_id, "worker_id": worker_id})
        return {"ok": True}

    @router.post("/workers/{worker_id}/fail")
    async def worker_fail(worker_id: str, body: dict[str, Any]):
        w = get_world()
        job_id = body.get("job_id")
        if not job_id or job_id not in w.jobs:
            raise HTTPException(404, "job not found")
        w.jobs[job_id].worker_error = body.get("error", "worker failed")
        await w.emit("worker_failed", {"job_id": job_id, "worker_id": worker_id})
        return {"ok": True}

    @router.get("/metrics")
    def metrics():
        return get_world().metrics()

    @router.get("/snapshot")
    def snapshot():
        return get_world().snapshot()

    @router.post("/links/{link_id}/disrupt")
    async def disrupt_link(link_id: str, body: DisruptBody):
        w = get_world()
        if link_id not in w.link_by_id:
            raise HTTPException(404, "link not found")
        result = w.disrupt_link(
            link_id, down=body.down, bandwidth_factor=body.bandwidth_factor, until=body.until
        )
        await w.emit("link_disrupted", result)
        return result

    @router.delete("/links/{link_id}/disrupt")
    async def clear_disrupt(link_id: str):
        w = get_world()
        w.clear_disruption(link_id)
        await w.emit("link_disrupted", {"link_id": link_id, "disruption": None})
        return {"ok": True}

    @router.post("/evaluations")
    async def create_eval(body: EvaluationBody):
        report = await run_evaluation(
            get_world(),
            seed=body.seed,
            n_jobs=body.n_jobs,
            policies=body.policies,
            max_steps=body.max_steps,
        )
        return report.model_dump()

    @router.get("/evaluations")
    def list_eval():
        w = get_world()
        if w.store:
            return w.store.list_evaluations()
        return list(w.evaluations.values())

    @router.get("/evaluations/{eid}")
    def get_eval(eid: str):
        w = get_world()
        if w.store:
            row = w.store.get_evaluation(eid)
            if row:
                return row
        row = w.evaluations.get(eid)
        if not row:
            raise HTTPException(404, "evaluation not found")
        return row

    @router.websocket("/ws")
    async def websocket_events(ws: WebSocket, since: int = 0):
        await ws.accept()
        if not authorize_websocket(ws):
            await ws.close(code=4401)
            return
        w = get_world()
        q = w.subscribe()
        try:
            await ws.send_json(
                {
                    "id": "hello",
                    "t": w.settings.t,
                    "type": "hello",
                    "seq": 0,
                    "payload": {"reality": "ephemeris real; bandwidth/compute simulated"},
                }
            )
            if since:
                for ev in w.events_since(since):
                    await ws.send_json(ev.model_dump())
            while True:
                ev = await q.get()
                await ws.send_json(ev.model_dump())
        except WebSocketDisconnect:
            pass
        finally:
            w.unsubscribe(q)

    return router
