"""Execute validated assistant actions against SimWorld. Planner is not called here."""

from __future__ import annotations

from typing import Any

from app.assistant.intents import ValidatedAction


async def execute(world: Any, action: ValidatedAction) -> dict[str, Any]:
    tool = action.tool
    args = action.args
    if tool == "read_state":
        return {"ok": True, "tool": tool, "result": _read_state(world, args.get("focus", "all"))}
    if tool == "explain_plan":
        return {"ok": True, "tool": tool, "result": _explain_plan(world, args.get("job_id"))}
    if tool == "play":
        await world.play()
        return {"ok": True, "tool": tool, "result": {"playing": True, "t": world.settings.t}}
    if tool == "pause":
        await world.pause()
        return {"ok": True, "tool": tool, "result": {"playing": False, "t": world.settings.t}}
    if tool == "submit_job":
        if args.get("preset"):
            result = await world.submit_thesis(args["preset"])
            return {"ok": True, "tool": tool, "result": _job_summary(result)}
        body = {
            "input_bytes": args["input_bytes"],
            "output_bytes": args["output_bytes"],
            "work": args["work"],
            "source_id": args["source_id"],
            "destination_id": args["destination_id"],
        }
        if "deadline_at" in args:
            body["deadline_at"] = args["deadline_at"]
        else:
            body["deadline_at"] = world.settings.t + float(args.get("deadline_offset_s", 3600))
        result = await world.submit_job(body)
        return {"ok": True, "tool": tool, "result": _job_summary(result)}
    if tool == "disrupt_link":
        lid = args["link_id"]
        if args.get("action") == "clear":
            world.clear_disruption(lid)
            await world.emit("link_disrupted", {"link_id": lid, "disruption": None})
            return {"ok": True, "tool": tool, "result": {"link_id": lid, "disruption": None}}
        out = world.disrupt_link(
            lid,
            down=True,
            bandwidth_factor=args.get("bandwidth_factor"),
            until=args.get("until"),
        )
        await world.emit("link_disrupted", out)
        return {"ok": True, "tool": tool, "result": out}
    return {"ok": False, "tool": tool, "error": "unhandled"}


def _read_state(world: Any, focus: str) -> dict[str, Any]:
    jobs = [
        {
            "id": j.id,
            "state": j.state.value if hasattr(j.state, "value") else j.state,
            "assigned_node_id": j.assigned_node_id,
            "plan_id": j.plan_id,
        }
        for j in world.jobs.values()
    ]
    links = [
        {
            "id": L.id,
            "kind": L.kind.value if hasattr(L.kind, "value") else L.kind,
            "up": L.up,
            "a": L.endpoint_a,
            "b": L.endpoint_b,
        }
        for L in world.links
    ]
    settings = {
        "t": world.settings.t,
        "playing": world.settings.playing,
        "speed": world.settings.speed,
        "disrupted_links": world.settings.disrupted_links,
    }
    out: dict[str, Any] = {"settings": settings} if focus in ("all", "settings") else {}
    if focus in ("all", "jobs"):
        out["jobs"] = jobs
    if focus in ("all", "links"):
        out["links"] = links
        out["links_up"] = sum(1 for L in world.links if L.up)
    return out


def _explain_plan(world: Any, job_id: str | None) -> dict[str, Any]:
    job = None
    if job_id:
        job = world.jobs.get(job_id)
    elif world.jobs:
        job = sorted(world.jobs.values(), key=lambda j: j.submitted_at, reverse=True)[0]
    if not job:
        return {"error": "no jobs to explain"}
    plan = world.plans.get(job.plan_id or "")
    if not plan:
        return {
            "job_id": job.id,
            "state": job.state.value if hasattr(job.state, "value") else job.state,
            "reason": job.fail_reason or "no plan",
        }
    bc = plan.baseline_comparison
    hops_in = [f"{h.from_id}→{h.to_id}" for h in plan.input_route]
    hops_out = [f"{h.from_id}→{h.to_id}" for h in plan.output_route]
    return {
        "job_id": job.id,
        "state": job.state.value if hasattr(job.state, "value") else job.state,
        "chosen_node_id": plan.compute_node_id,
        "estimated_cost": plan.estimated_cost,
        "estimated_completion": plan.estimated_completion,
        "input_route": hops_in,
        "output_route": hops_out,
        "baseline": bc.model_dump() if bc else None,
        "reasons": list(bc.reason_codes) if bc else [],
        "note": "Placement came from the deterministic planner, not the assistant.",
    }


def _job_summary(result: dict[str, Any]) -> dict[str, Any]:
    job = result.get("job") or {}
    plan = result.get("plan") or {}
    return {
        "job_id": job.get("id"),
        "state": job.get("state"),
        "assigned_node_id": job.get("assigned_node_id"),
        "estimated_cost": plan.get("estimated_cost"),
        "estimated_completion": plan.get("estimated_completion"),
        "error": result.get("error"),
        "preset": (result.get("preset") or {}).get("name") if isinstance(result.get("preset"), dict) else result.get("preset"),
        "sought_t": result.get("sought_t"),
    }
