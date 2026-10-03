"""In-memory simulation world: clock, links, transfers, jobs, workers."""

from __future__ import annotations

import asyncio
import json
import math
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.models.types import (
    ComputeNode,
    Event,
    GroundStation,
    Job,
    JobState,
    LinkConfig,
    LinkKind,
    NodeKind,
    OrbitalRecord,
    Plan,
    Reservation,
    Settings,
    Transfer,
    TransferDirection,
    TransferState,
    WorkerStatus,
)
from app.orbit.propagate import OrbitEngine, elevation_deg, geodetic_to_ecef, range_m
from app.planner.placement import PlacementPlanner
from app.topology import build_topology

EventCallback = Callable[[Event], Awaitable[None]]

WORKER_SCRIPT = Path(__file__).resolve().parent.parent / "workers" / "image_batch.py"


class SimWorld:
    def __init__(self):
        topo = build_topology()
        self.records: list[OrbitalRecord] = topo["records"]
        self.epoch: datetime = topo["epoch"]
        self.nodes: list[ComputeNode] = topo["nodes"]
        self.stations: list[GroundStation] = topo["stations"]
        self.links: list[LinkConfig] = topo["links"]
        self.orbit: OrbitEngine = topo["orbit_engine"]

        self.node_by_id = {n.id: n for n in self.nodes}
        self.station_by_id = {s.id: s for s in self.stations}
        self.link_by_id = {L.id: L for L in self.links}
        self.record_by_id = {r.id: r for r in self.records}

        self.settings = Settings(
            sim_step_s=5.0,
            plan_horizon_s=7200.0,
            epoch_utc=self.epoch.isoformat().replace("+00:00", "Z"),
            playing=False,
            speed=10.0,
            t=0.0,
            disrupted_links={},
        )
        self.jobs: dict[str, Job] = {}
        self.plans: dict[str, Plan] = {}
        self.transfers: dict[str, Transfer] = {}
        self.reservations: list[Reservation] = []
        self.link_reservations: dict[str, list[tuple[float, float, int]]] = {}
        self.events: list[Event] = []
        self._event_subs: list[asyncio.Queue] = []
        self._tick_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.workers: dict[str, WorkerStatus] = {
            "worker-local-1": WorkerStatus(id="worker-local-1", state="idle")
        }
        self._worker_procs: dict[str, asyncio.subprocess.Process] = {}
        self._worker_meta: dict[str, dict[str, Any]] = {}
        self._worker_tasks: dict[str, asyncio.Task] = {}
        self._prev_link_up: dict[str, bool] = {L.id: L.up for L in self.links}
        self._update_positions_and_links()

    # ── subscriptions ──────────────────────────────────────────────
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._event_subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._event_subs:
            self._event_subs.remove(q)

    async def emit(self, type_: str, payload: dict[str, Any] | None = None) -> Event:
        ev = Event(
            id=f"ev-{uuid.uuid4().hex[:12]}",
            t=self.settings.t,
            type=type_,
            payload=payload or {},
        )
        self.events.append(ev)
        if len(self.events) > 5000:
            self.events = self.events[-4000:]
        for q in list(self._event_subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    pass
        return ev

    # ── topology helpers ───────────────────────────────────────────
    def endpoint_ecef(self, eid: str, t: Optional[float] = None) -> Optional[tuple[float, float, float]]:
        t = self.settings.t if t is None else t
        if eid in self.station_by_id:
            s = self.station_by_id[eid]
            return geodetic_to_ecef(s.lat, s.lon, s.alt_m)
        n = self.node_by_id.get(eid)
        if not n:
            return None
        if n.kind == NodeKind.earth:
            return geodetic_to_ecef(n.lat or 0, n.lon or 0, (n.alt_km or 0) * 1000)
        if n.orbital_record_id:
            return self.orbit.position_ecef_m(n.orbital_record_id, t)
        return None

    def link_up_at(self, link: LinkConfig, t: float) -> bool:
        d = self.settings.disrupted_links.get(link.id) or {}
        if d.get("down"):
            until = d.get("until")
            if until is None or t < float(until):
                return False
        factor = float(d.get("bandwidth_factor", 1.0))
        if factor <= 0:
            return False

        if link.kind == LinkKind.terrestrial:
            return True
        if link.kind == LinkKind.ground_space:
            gs_id = link.endpoint_a if link.endpoint_a in self.station_by_id else link.endpoint_b
            orb_id = link.endpoint_b if gs_id == link.endpoint_a else link.endpoint_a
            gs = self.station_by_id[gs_id]
            orb = self.node_by_id[orb_id]
            ecef = self.orbit.position_ecef_m(orb.orbital_record_id, t)  # type: ignore
            if ecef is None:
                return False
            el = elevation_deg(gs.lat, gs.lon, gs.alt_m, ecef)
            min_el = link.rules.get("min_elevation_deg", gs.min_elevation_deg)
            if el < min_el:
                return False
            max_range = link.rules.get("max_range_km", gs.max_range_km)
            if max_range is not None:
                s_ecef = geodetic_to_ecef(gs.lat, gs.lon, gs.alt_m)
                if range_m(s_ecef, ecef) > float(max_range) * 1000:
                    return False
            return True
        if link.kind == LinkKind.isl:
            a = self.node_by_id[link.endpoint_a]
            b = self.node_by_id[link.endpoint_b]
            ea = self.orbit.position_ecef_m(a.orbital_record_id, t)  # type: ignore
            eb = self.orbit.position_ecef_m(b.orbital_record_id, t)  # type: ignore
            if ea is None or eb is None:
                return False
            max_km = float(link.rules.get("max_range_km", 4000))
            return range_m(ea, eb) <= max_km * 1000
        return False

    def effective_bandwidth(self, link: LinkConfig) -> float:
        d = self.settings.disrupted_links.get(link.id) or {}
        return link.bandwidth_bps * float(d.get("bandwidth_factor", 1.0))

    def _update_positions_and_links(self) -> list[Event]:
        t = self.settings.t
        for n in self.nodes:
            if n.kind == NodeKind.orbital and n.orbital_record_id:
                lla = self.orbit.position_lla(n.orbital_record_id, t)
                eci = self.orbit.position_eci_km(n.orbital_record_id, t)
                n.position_lla = lla
                n.position_eci_m = [eci[0] * 1000, eci[1] * 1000, eci[2] * 1000] if eci else None
            elif n.kind == NodeKind.earth:
                n.position_lla = {"lat": n.lat or 0, "lon": n.lon or 0, "alt_km": n.alt_km or 0}

        emitted: list[Event] = []
        for L in self.links:
            up = self.link_up_at(L, t)
            prev = self._prev_link_up.get(L.id, False)
            L.up = up
            if up != prev:
                # note: emit is async; collect sync markers — caller emits
                emitted.append(
                    Event(
                        id=f"ev-{uuid.uuid4().hex[:12]}",
                        t=t,
                        type="link_up" if up else "link_down",
                        payload={"link_id": L.id, "a": L.endpoint_a, "b": L.endpoint_b},
                    )
                )
            self._prev_link_up[L.id] = up
        return emitted

    def _planner(self) -> PlacementPlanner:
        return PlacementPlanner(
            nodes=self.nodes,
            stations=self.stations,
            links=self.links,
            orbit=self.orbit,
            node_by_id=self.node_by_id,
            station_by_id=self.station_by_id,
            link_by_id=self.link_by_id,
            reservations=self.reservations,
            link_reservations=self.link_reservations,
            disrupted=self.settings.disrupted_links,
            sim_step_s=self.settings.sim_step_s,
            plan_horizon_s=self.settings.plan_horizon_s,
        )

    # ── public API ops ─────────────────────────────────────────────
    async def submit_job(self, body: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            job = Job(
                id=f"job-{uuid.uuid4().hex[:10]}",
                submitted_at=self.settings.t,
                input_bytes=int(body.get("input_bytes", 5_000_000)),
                output_bytes=int(body.get("output_bytes", 1_000_000)),
                work=float(body.get("work", 200.0)),
                deadline_at=body.get("deadline_at"),
                source_id=body.get("source_id", "gs-ashburn"),
                destination_id=body.get("destination_id", "gs-ashburn"),
                state=JobState.submitted,
                preset=body.get("preset"),
                data_location_id=body.get("source_id", "gs-ashburn"),
            )
            if job.deadline_at is not None:
                job.deadline_at = float(job.deadline_at)

            self.jobs[job.id] = job
            await self.emit("job_state", {"job_id": job.id, "state": job.state.value})

            planner = self._planner()
            plan, baseline, err = planner.plan_job(job, self.settings.t)
            if plan is None:
                job.state = JobState.failed
                job.fail_reason = err or "placement failed"
                await self.emit(
                    "job_state",
                    {"job_id": job.id, "state": job.state.value, "reason": job.fail_reason},
                )
                return {
                    "job": job.model_dump(),
                    "plan": None,
                    "baseline_comparison": baseline.model_dump() if baseline else None,
                    "error": job.fail_reason,
                }

            planner.enrich_reasons(plan, job)
            plan.job_id = job.id
            self.plans[plan.id] = plan
            job.plan_id = plan.id
            job.assigned_node_id = plan.compute_node_id
            job.state = JobState.planned
            self.reservations.append(
                Reservation(
                    job_id=job.id,
                    node_id=plan.compute_node_id,
                    start=plan.compute_start,
                    end=plan.compute_end,
                )
            )
            self.node_by_id[plan.compute_node_id].available_at = max(
                self.node_by_id[plan.compute_node_id].available_at, plan.compute_end
            )
            await self.emit(
                "plan_created",
                {"job_id": job.id, "plan": plan.model_dump()},
            )
            await self.emit("job_state", {"job_id": job.id, "state": job.state.value})

            # Start input transfer
            await self._begin_input(job, plan)
            return {
                "job": job.model_dump(),
                "plan": plan.model_dump(),
                "baseline_comparison": plan.baseline_comparison.model_dump()
                if plan.baseline_comparison
                else None,
            }

    async def _begin_input(self, job: Job, plan: Plan) -> None:
        if not plan.input_route:
            job.state = JobState.queued
            job.data_location_id = plan.compute_node_id
            await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
            return
        hop = plan.input_route[0]
        tr = Transfer(
            id=f"xfer-{uuid.uuid4().hex[:10]}",
            job_id=job.id,
            direction=TransferDirection.input,
            from_id=hop.from_id,
            to_id=hop.to_id,
            bytes_total=hop.bytes,
            bytes_sent=0,
            state=TransferState.pending,
            active_link_id=hop.link_id,
            hop_index=0,
        )
        self.transfers[tr.id] = tr
        job.state = JobState.input_transfer
        await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
        await self.emit(
            "transfer_progress",
            {"transfer": tr.model_dump()},
        )

    async def _begin_output(self, job: Job, plan: Plan) -> None:
        if not plan.output_route:
            job.state = JobState.completed
            job.actual_completion = self.settings.t
            job.actual_cost = plan.estimated_cost
            await self.emit(
                "job_state",
                {
                    "job_id": job.id,
                    "state": job.state.value,
                    "actual_completion": job.actual_completion,
                    "actual_cost": job.actual_cost,
                },
            )
            return
        hop = plan.output_route[0]
        tr = Transfer(
            id=f"xfer-{uuid.uuid4().hex[:10]}",
            job_id=job.id,
            direction=TransferDirection.output,
            from_id=hop.from_id,
            to_id=hop.to_id,
            bytes_total=hop.bytes,
            bytes_sent=0,
            state=TransferState.pending,
            active_link_id=hop.link_id,
            hop_index=0,
        )
        self.transfers[tr.id] = tr
        job.state = JobState.output_transfer
        job.data_location_id = hop.from_id
        await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
        await self.emit("transfer_progress", {"transfer": tr.model_dump()})

    # ── tick ───────────────────────────────────────────────────────
    async def step(self) -> None:
        async with self._lock:
            await self._step_unlocked()

    async def _step_unlocked(self) -> None:
        step = self.settings.sim_step_s
        self.settings.t += step
        link_events = self._update_positions_and_links()
        for ev in link_events:
            self.events.append(ev)
            for q in list(self._event_subs):
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    pass

        await self._progress_transfers(step)
        await self._progress_compute()
        await self._poll_workers()
        await self.emit(
            "tick",
            {
                "t": self.settings.t,
                "positions": {
                    n.id: n.position_lla for n in self.nodes if n.position_lla
                },
                "links_up": [L.id for L in self.links if L.up],
            },
        )

    async def _progress_transfers(self, step: float) -> None:
        for tr in list(self.transfers.values()):
            if tr.state in (TransferState.completed, TransferState.failed):
                continue
            job = self.jobs.get(tr.job_id)
            if not job or job.state in (JobState.canceled, JobState.failed, JobState.completed):
                continue
            link = self.link_by_id.get(tr.active_link_id or "")
            if not link:
                tr.state = TransferState.failed
                continue
            up = link.up
            if not up:
                if tr.state == TransferState.active:
                    tr.state = TransferState.paused
                    await self.emit(
                        "transfer_progress",
                        {"transfer": tr.model_dump(), "reason": "link_down"},
                    )
                continue

            # Exclusive: only one active transfer per link
            busy = any(
                o.id != tr.id
                and o.state == TransferState.active
                and o.active_link_id == link.id
                for o in self.transfers.values()
            )
            if busy and tr.state != TransferState.active:
                continue
            if busy and tr.state == TransferState.active:
                # already owner
                pass
            elif busy:
                continue

            tr.state = TransferState.active
            bw = self.effective_bandwidth(link)
            bytes_this = bw * step / 8.0
            tr.bytes_sent = min(tr.bytes_total, int(tr.bytes_sent + bytes_this))
            await self.emit("transfer_progress", {"transfer": tr.model_dump()})

            if tr.bytes_sent >= tr.bytes_total:
                tr.state = TransferState.completed
                job.data_location_id = tr.to_id
                await self.emit("transfer_progress", {"transfer": tr.model_dump()})
                await self._advance_route(job, tr)

    async def _advance_route(self, job: Job, tr: Transfer) -> None:
        plan = self.plans.get(job.plan_id or "")
        if not plan:
            return
        route = plan.input_route if tr.direction == TransferDirection.input else plan.output_route
        next_i = tr.hop_index + 1
        if next_i < len(route):
            hop = route[next_i]
            new_tr = Transfer(
                id=f"xfer-{uuid.uuid4().hex[:10]}",
                job_id=job.id,
                direction=tr.direction,
                from_id=hop.from_id,
                to_id=hop.to_id,
                bytes_total=hop.bytes,
                bytes_sent=0,
                state=TransferState.pending,
                active_link_id=hop.link_id,
                hop_index=next_i,
            )
            self.transfers[new_tr.id] = new_tr
            await self.emit("transfer_progress", {"transfer": new_tr.model_dump()})
            return

        # Route complete
        if tr.direction == TransferDirection.input:
            job.state = JobState.queued
            await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
        else:
            job.state = JobState.completed
            job.actual_completion = self.settings.t
            job.actual_cost = plan.estimated_cost
            await self.emit(
                "job_state",
                {
                    "job_id": job.id,
                    "state": job.state.value,
                    "actual_completion": job.actual_completion,
                    "actual_cost": job.actual_cost,
                    "estimated_completion": plan.estimated_completion,
                    "estimated_cost": plan.estimated_cost,
                },
            )

    async def _progress_compute(self) -> None:
        t = self.settings.t
        for job in self.jobs.values():
            if job.state not in (JobState.queued, JobState.running):
                continue
            plan = self.plans.get(job.plan_id or "")
            if not plan:
                continue
            if job.state == JobState.queued and t + 1e-9 >= plan.compute_start:
                job.state = JobState.running
                await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
                await self._start_worker(job)
            if job.state == JobState.running:
                sim_done = t + 1e-9 >= plan.compute_end
                if job.worker_error:
                    job.state = JobState.failed
                    job.fail_reason = job.worker_error
                    await self.emit(
                        "job_state",
                        {"job_id": job.id, "state": job.state.value, "reason": job.fail_reason},
                    )
                    continue
                if sim_done and job.worker_done:
                    await self._begin_output(job, plan)
                elif job.worker_done and not sim_done:
                    # hold until sim compute_end
                    pass
                elif sim_done and not job.worker_done:
                    # slip: extend compute_end modestly each step until worker done
                    old_end = plan.compute_end
                    plan.compute_end = t + self.settings.sim_step_s
                    for r in self.reservations:
                        if r.job_id == job.id:
                            r.end = plan.compute_end
                    await self.emit(
                        "schedule_slip",
                        {
                            "job_id": job.id,
                            "old_compute_end": old_end,
                            "new_compute_end": plan.compute_end,
                        },
                    )

    async def _start_worker(self, job: Job) -> None:
        if job.worker_started:
            return
        job.worker_started = True
        wid = "worker-local-1"
        if self.workers[wid].state == "busy":
            wid = f"worker-{job.id}"
            self.workers[wid] = WorkerStatus(id=wid, state="idle")
        self.workers[wid].state = "busy"
        self.workers[wid].job_id = job.id
        out_dir = Path(tempfile.mkdtemp(prefix=f"sdc-{job.id}-"))
        self._worker_meta[job.id] = {"worker_id": wid, "out_dir": str(out_dir)}
        self._worker_tasks[job.id] = asyncio.create_task(self._run_worker(job, wid, out_dir))
        await self.emit("worker_started", {"job_id": job.id, "worker_id": wid})

    async def _run_worker(self, job: Job, wid: str, out_dir: Path) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(WORKER_SCRIPT),
                "--job-id",
                job.id,
                "--work",
                str(job.work),
                "--out",
                str(out_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._worker_procs[job.id] = proc
            stdout_b, stderr_b = await proc.communicate()
            stdout = stdout_b.decode() if stdout_b else ""
            stderr = stderr_b.decode() if stderr_b else ""
            try:
                data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
            except Exception:
                data = {"ok": False, "error": stderr or "bad worker output"}
            if proc.returncode != 0 or not data.get("ok", False):
                job.worker_error = data.get("error") or stderr or f"exit {proc.returncode}"
                await self.emit("worker_failed", {"job_id": job.id, "error": job.worker_error})
            else:
                job.worker_done = True
                await self.emit("worker_complete", {"job_id": job.id, "result": data})
        except Exception as e:
            job.worker_error = str(e)
            await self.emit("worker_failed", {"job_id": job.id, "error": job.worker_error})
        finally:
            self._worker_procs.pop(job.id, None)
            self._worker_tasks.pop(job.id, None)
            if wid in self.workers:
                self.workers[wid].state = "idle"
                self.workers[wid].job_id = None

    async def _poll_workers(self) -> None:
        # Workers complete via asyncio tasks; yield so they can progress.
        await asyncio.sleep(0)

    async def play(self) -> None:
        self.settings.playing = True
        if self._tick_task is None or self._tick_task.done():
            self._tick_task = asyncio.create_task(self._play_loop())
        await self.emit("metric", {"playing": True})

    async def pause(self) -> None:
        self.settings.playing = False
        await self.emit("metric", {"playing": False})

    async def _play_loop(self) -> None:
        try:
            while self.settings.playing:
                await self.step()
                delay = max(0.01, self.settings.sim_step_s / max(self.settings.speed, 0.1))
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self.settings.playing = False
            raise

    async def seek(self, t: float) -> None:
        """Jump sim clock (no transfer replay). Used for thesis scenario setup."""
        async with self._lock:
            self.settings.t = max(0.0, float(t))
            for ev in self._update_positions_and_links():
                self.events.append(ev)
            await self.emit("metric", {"seek": True, "t": self.settings.t})

    async def reset(self) -> None:
        async with self._lock:
            self.settings.playing = False
            tick = self._tick_task
            self._tick_task = None
            if tick is not None and not tick.done():
                tick.cancel()
            for task in list(self._worker_tasks.values()):
                task.cancel()
            for proc in list(self._worker_procs.values()):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            self._worker_procs.clear()
            self._worker_tasks.clear()
            self._worker_meta.clear()
            self.jobs.clear()
            self.plans.clear()
            self.transfers.clear()
            self.reservations.clear()
            self.link_reservations.clear()
            self.events.clear()
            self.settings.t = 0.0
            self.settings.disrupted_links.clear()
            for n in self.nodes:
                n.available_at = 0.0
            for w in self.workers.values():
                w.state = "idle"
                w.job_id = None
            self._update_positions_and_links()
            await self.emit("metric", {"reset": True, "t": 0.0})

    async def cancel_job(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        if job.state in (JobState.completed, JobState.failed, JobState.canceled):
            return job
        job.state = JobState.canceled
        if job_id in self._worker_procs:
            self._worker_procs[job_id].kill()
            del self._worker_procs[job_id]
        await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
        return job

    def disrupt_link(self, link_id: str, down: bool = True, bandwidth_factor: Optional[float] = None, until: Optional[float] = None) -> dict:
        cfg = dict(self.settings.disrupted_links.get(link_id) or {})
        if down:
            cfg["down"] = True
        if bandwidth_factor is not None:
            cfg["bandwidth_factor"] = bandwidth_factor
            if bandwidth_factor > 0 and not down:
                cfg.pop("down", None)
        if until is not None:
            cfg["until"] = until
        if not down and bandwidth_factor is None:
            cfg.pop("down", None)
        if not cfg:
            self.settings.disrupted_links.pop(link_id, None)
        else:
            self.settings.disrupted_links[link_id] = cfg
        return {"link_id": link_id, "disruption": self.settings.disrupted_links.get(link_id)}

    def clear_disruption(self, link_id: str) -> None:
        self.settings.disrupted_links.pop(link_id, None)

    async def try_replan(self, job_id: str) -> dict:
        async with self._lock:
            job = self.jobs[job_id]
            plan = self.plans.get(job.plan_id or "")
            if not plan or not job.assigned_node_id:
                return {"ok": False, "error": "no plan"}
            phase = "input" if job.state in (JobState.input_transfer, JobState.planned) else "output"
            if job.state not in (
                JobState.input_transfer,
                JobState.output_transfer,
                JobState.planned,
            ):
                return {"ok": False, "error": f"cannot replan in state {job.state}"}
            data_at = job.data_location_id or job.source_id
            planner = self._planner()
            new_plan = planner.replan_routes(job, plan, data_at, phase, self.settings.t)
            if new_plan is None:
                job.state = JobState.failed
                job.fail_reason = "replan infeasible; assigned node fixed"
                await self.emit(
                    "replan",
                    {"job_id": job.id, "ok": False, "reason": job.fail_reason},
                )
                await self.emit("job_state", {"job_id": job.id, "state": job.state.value})
                return {"ok": False, "error": job.fail_reason}
            self.plans[new_plan.id] = new_plan
            # refresh reservations for this job
            self.reservations = [r for r in self.reservations if r.job_id != job.id]
            self.reservations.append(
                Reservation(
                    job_id=job.id,
                    node_id=new_plan.compute_node_id,
                    start=new_plan.compute_start,
                    end=new_plan.compute_end,
                )
            )
            await self.emit("replan", {"job_id": job.id, "ok": True, "plan": new_plan.model_dump()})
            # restart current phase transfer from data_at
            for tr in list(self.transfers.values()):
                if tr.job_id == job.id and tr.state not in (TransferState.completed,):
                    tr.state = TransferState.failed
            if phase == "input":
                await self._begin_input(job, new_plan)
            else:
                await self._begin_output(job, new_plan)
            return {"ok": True, "plan": new_plan.model_dump()}

    def snapshot(self) -> dict[str, Any]:
        return {
            "settings": self.settings.model_dump(),
            "nodes": [n.model_dump() for n in self.nodes],
            "stations": [s.model_dump() for s in self.stations],
            "links": [L.model_dump() for L in self.links],
            "jobs": [j.model_dump() for j in self.jobs.values()],
            "plans": [p.model_dump() for p in self.plans.values()],
            "transfers": [t.model_dump() for t in self.transfers.values()],
            "workers": [w.model_dump() for w in self.workers.values()],
            "reality": {
                "ephemeris": "real_tle_sgp4",
                "contacts": "computed_from_real_geometry",
                "compute_capacity_pricing": "simulated",
                "link_bandwidth_pricing": "simulated",
            },
        }

    def metrics(self) -> dict[str, Any]:
        by_state: dict[str, int] = {}
        for j in self.jobs.values():
            by_state[j.state.value] = by_state.get(j.state.value, 0) + 1
        completed = [j for j in self.jobs.values() if j.state == JobState.completed and j.plan_id]
        delays = []
        cost_deltas = []
        for j in completed:
            p = self.plans[j.plan_id]  # type: ignore
            if j.actual_completion is not None:
                delays.append(j.actual_completion - p.estimated_completion)
            if p.baseline_comparison:
                cost_deltas.append(p.estimated_cost - p.baseline_comparison.baseline_cost)
        links_up = sum(1 for L in self.links if L.up)
        return {
            "jobs_by_state": by_state,
            "mean_completion_delay_s": sum(delays) / len(delays) if delays else 0.0,
            "mean_cost_vs_baseline": sum(cost_deltas) / len(cost_deltas) if cost_deltas else 0.0,
            "links_up": links_up,
            "links_total": len(self.links),
            "t": self.settings.t,
            "active_transfers": sum(
                1 for t in self.transfers.values() if t.state == TransferState.active
            ),
        }

    def _contact_windows(self, gs_id: str, orb_id: str, t0: float, t1: float) -> list[tuple[float, float]]:
        link = next(
            (
                L
                for L in self.links
                if L.kind == LinkKind.ground_space
                and {L.endpoint_a, L.endpoint_b} == {gs_id, orb_id}
            ),
            None,
        )
        if not link:
            return []
        step = self.settings.sim_step_s
        windows: list[tuple[float, float]] = []
        t = t0
        in_win = False
        start = t
        while t <= t1:
            up = self.link_up_at(link, t)
            if up and not in_win:
                in_win = True
                start = t
            elif not up and in_win:
                in_win = False
                windows.append((start, t))
            t += step
        if in_win:
            windows.append((start, t))
        return windows

    def thesis_presets(self) -> dict[str, Any]:
        """Compute Case A/B parameters from real SGP4 contact geometry."""
        cheap_id = min(self.nodes, key=lambda n: n.price_per_work).id
        gs = "gs-ashburn"
        # Scan a full day from epoch for ISS/Ashburn windows
        windows = self._contact_windows(gs, cheap_id, 0.0, 86400.0)

        case_a = {
            "name": "case_a_cheap_loses",
            "label": "Case A — cheap orbital loses (contact too late)",
            "source_id": gs,
            "destination_id": gs,
            "input_bytes": 8_000_000,
            "output_bytes": 1_500_000,
            "work": 180.0,
            "hint": "Seek to just after a pass; tight deadline cannot wait for the next ISS contact.",
        }
        case_b = {
            "name": "case_b_cheap_wins",
            "label": "Case B — cheap orbital wins",
            "source_id": gs,
            "destination_id": gs,
            "input_bytes": 8_000_000,
            "output_bytes": 1_500_000,
            "work": 180.0,
            "hint": "Seek to ~60s before a pass; cheap ISS meets deadline at lowest cost.",
        }

        # Prefer a gap after an Ashburn pass. Next cheap-node reachability may be via
        # another GS (store-and-forward through Earth), so scan all stations.
        gap_t = None
        for i, (s, e) in enumerate(windows[:-1]):
            if windows[i + 1][0] - e >= 600:
                gap_t = e + 60
                break
        if gap_t is None and windows:
            gap_t = windows[0][1] + 60 if windows[0][0] < 1200 else 60.0

        if gap_t is not None:
            next_any = None
            for station in self.stations:
                for s, e in self._contact_windows(station.id, cheap_id, gap_t, gap_t + 20000):
                    if s >= gap_t:
                        next_any = s if next_any is None else min(next_any, s)
                        break
            # Deadline before next contact on any GS — Earth finishes terrestrially; ISS cannot
            if next_any is not None and next_any - gap_t > 90:
                case_a["recommended_sim_t"] = gap_t
                case_a["deadline_offset_s"] = min(180.0, (next_any - gap_t) * 0.4)
                case_a["deadline_at"] = gap_t + case_a["deadline_offset_s"]
            else:
                case_a["recommended_sim_t"] = gap_t
                case_a["deadline_offset_s"] = 120.0
                case_a["deadline_at"] = gap_t + 120.0
        else:
            case_a["recommended_sim_t"] = 0.0
            case_a["deadline_at"] = 300.0
            case_a["deadline_offset_s"] = 300.0

        # Case B: 60s before a solid window
        win_b = None
        for s, e in windows:
            if e - s >= 200:
                win_b = (s, e)
                break
        if win_b is None and windows:
            win_b = windows[0]
        if win_b:
            case_b["recommended_sim_t"] = max(0.0, win_b[0] - 60)
            case_b["deadline_at"] = case_b["recommended_sim_t"] + 3600
            case_b["deadline_offset_s"] = 3600.0
        else:
            case_b["recommended_sim_t"] = 30000.0
            case_b["deadline_at"] = 34000.0
            case_b["deadline_offset_s"] = 4000.0

        return {
            "cheap_node_id": cheap_id,
            "contact_windows_gs_ashburn": windows[:8],
            "case_a": case_a,
            "case_b": case_b,
            "objective": (
                "Prefer feasible-by-deadline then lower cost; "
                "else earlier completion then cost"
            ),
        }

    async def submit_thesis(self, case: str) -> dict[str, Any]:
        """Seek to scenario time, reset jobs, submit Case A or B."""
        presets = self.thesis_presets()
        key = "case_a" if case in ("a", "case_a", "case_a_cheap_loses") else "case_b"
        spec = presets[key]
        await self.reset()
        await self.seek(float(spec["recommended_sim_t"]))
        body = {
            "input_bytes": spec["input_bytes"],
            "output_bytes": spec["output_bytes"],
            "work": spec["work"],
            "deadline_at": float(spec["recommended_sim_t"]) + float(spec["deadline_offset_s"]),
            "source_id": spec["source_id"],
            "destination_id": spec["destination_id"],
            "preset": spec["name"],
        }
        result = await self.submit_job(body)
        result["preset"] = spec
        result["sought_t"] = self.settings.t
        return result
