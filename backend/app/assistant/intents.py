"""Allowed assistant tools and strict validation.

The assistant never chooses a compute node. Job submit goes through
``SimWorld.submit_job`` / thesis presets so placement stays deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

ALLOWED_TOOLS = (
    "read_state",
    "explain_plan",
    "submit_job",
    "play",
    "pause",
    "disrupt_link",
)

TOOL_ALIASES = {
    "get_state": "read_state",
    "status": "read_state",
    "snapshot": "read_state",
    "explain": "explain_plan",
    "explain_job": "explain_plan",
    "show_plan": "explain_plan",
    "submit": "submit_job",
    "place_job": "submit_job",
    "run_job": "submit_job",
    "start": "play",
    "resume": "play",
    "stop": "pause",
    "halt": "pause",
    "disrupt": "disrupt_link",
    "drop_link": "disrupt_link",
    "restore_link": "disrupt_link",
}

ALLOWED_PER_TOOL: dict[str, frozenset[str]] = {
    "read_state": frozenset({"focus"}),
    "explain_plan": frozenset({"job_id"}),
    "submit_job": frozenset(
        {
            "input_bytes",
            "output_bytes",
            "work",
            "deadline_at",
            "deadline_offset_s",
            "source_id",
            "destination_id",
            "preset",
        }
    ),
    "play": frozenset(),
    "pause": frozenset(),
    "disrupt_link": frozenset({"link_id", "action", "down", "bandwidth_factor", "until"}),
}

FORBIDDEN_SUBMIT_KEYS = frozenset(
    {
        "assigned_node_id",
        "compute_node_id",
        "node_id",
        "plan_id",
        "baseline_node_id",
        "reservations",
        "input_route",
        "output_route",
        "force_node",
    }
)

FOCUS_VALUES = frozenset({"jobs", "links", "settings", "all"})
DISRUPT_ACTIONS = frozenset({"down", "clear"})
THESIS_PRESETS = frozenset({"a", "b", "case_a", "case_b", "case_a_cheap_loses", "case_b_cheap_wins"})

MAX_INPUT_BYTES = 500_000_000
MAX_OUTPUT_BYTES = 500_000_000
MAX_WORK = 1_000_000.0
MIN_DEADLINE_OFFSET = 1.0
MAX_DEADLINE_OFFSET = 86_400.0

DEFAULT_JOB = {
    "input_bytes": 5_000_000,
    "output_bytes": 1_000_000,
    "work": 200.0,
    "deadline_offset_s": 3600.0,
    "source_id": "gs-ashburn",
    "destination_id": "gs-ashburn",
}


@dataclass(frozen=True)
class WorldCatalog:
    link_ids: frozenset[str] = field(default_factory=frozenset)
    job_ids: frozenset[str] = field(default_factory=frozenset)
    station_ids: frozenset[str] = field(default_factory=frozenset)
    node_ids: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_world(cls, world: Any) -> "WorldCatalog":
        return cls(
            link_ids=frozenset(world.link_by_id),
            job_ids=frozenset(world.jobs),
            station_ids=frozenset(world.station_by_id),
            node_ids=frozenset(world.node_by_id),
        )


@dataclass
class ValidatedAction:
    tool: str
    args: dict[str, Any]


@dataclass
class ValidationError:
    tool: str
    message: str
    args: dict[str, Any] = field(default_factory=dict)


def canonicalize_tool(name: str) -> Optional[str]:
    raw = (name or "").strip()
    if not raw:
        return None
    key = raw.lower().replace("-", "_").replace(" ", "_")
    if key in ALLOWED_TOOLS:
        return key
    return TOOL_ALIASES.get(key)


def _as_dict(args: Any) -> dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, dict):
        return dict(args)
    return {}


def validate_intent(
    name: str,
    args: Any,
    catalog: Optional[WorldCatalog] = None,
) -> ValidatedAction | ValidationError:
    catalog = catalog or WorldCatalog()
    raw_args = _as_dict(args)
    tool = canonicalize_tool(name)
    if tool is None:
        return ValidationError(tool=name or "unknown", message="unknown tool", args=raw_args)

    forbidden = FORBIDDEN_SUBMIT_KEYS.intersection(raw_args)
    if forbidden:
        return ValidationError(
            tool=tool,
            message=f"planner override rejected: {sorted(forbidden)}",
            args=raw_args,
        )

    extra = set(raw_args) - ALLOWED_PER_TOOL[tool]
    if extra:
        return ValidationError(
            tool=tool,
            message=f"unexpected fields: {sorted(extra)}",
            args=raw_args,
        )

    if tool == "read_state":
        focus = raw_args.get("focus", "all")
        if focus not in FOCUS_VALUES:
            return ValidationError(tool=tool, message="focus must be jobs, links, settings, or all")
        return ValidatedAction(tool, {"focus": focus})

    if tool == "explain_plan":
        job_id = raw_args.get("job_id")
        if job_id is not None:
            if not isinstance(job_id, str) or not job_id:
                return ValidationError(tool=tool, message="job_id must be a non-empty string")
            if catalog.job_ids and job_id not in catalog.job_ids:
                return ValidationError(tool=tool, message=f"unknown job_id: {job_id}")
        return ValidatedAction(tool, {"job_id": job_id} if job_id else {})

    if tool in ("play", "pause"):
        return ValidatedAction(tool, {})

    if tool == "submit_job":
        return _validate_submit(raw_args, catalog)

    if tool == "disrupt_link":
        return _validate_disrupt(raw_args, catalog)

    return ValidationError(tool=tool, message="unhandled tool")


def _validate_submit(raw: dict[str, Any], catalog: WorldCatalog) -> ValidatedAction | ValidationError:
    args: dict[str, Any] = {}
    preset = raw.get("preset")
    if preset is not None:
        key = str(preset).strip().lower()
        if key in ("a", "case_a", "case_a_cheap_loses", "cheap_loses"):
            args["preset"] = "a"
        elif key in ("b", "case_b", "case_b_cheap_wins", "cheap_wins"):
            args["preset"] = "b"
        else:
            return ValidationError(tool="submit_job", message=f"unknown preset: {preset}")
        return ValidatedAction("submit_job", args)

    def _int_field(name: str, default: int, lo: int, hi: int) -> int | ValidationError:
        val = raw.get(name, default)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return ValidationError(tool="submit_job", message=f"{name} must be a number")
        ival = int(val)
        if ival < lo or ival > hi:
            return ValidationError(tool="submit_job", message=f"{name} out of range")
        return ival

    def _float_field(name: str, default: float, lo: float, hi: float) -> float | ValidationError:
        val = raw.get(name, default)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return ValidationError(tool="submit_job", message=f"{name} must be a number")
        fval = float(val)
        if fval < lo or fval > hi:
            return ValidationError(tool="submit_job", message=f"{name} out of range")
        return fval

    ib = _int_field("input_bytes", DEFAULT_JOB["input_bytes"], 1, MAX_INPUT_BYTES)
    if isinstance(ib, ValidationError):
        return ib
    ob = _int_field("output_bytes", DEFAULT_JOB["output_bytes"], 1, MAX_OUTPUT_BYTES)
    if isinstance(ob, ValidationError):
        return ob
    work = _float_field("work", DEFAULT_JOB["work"], 0.001, MAX_WORK)
    if isinstance(work, ValidationError):
        return work

    args["input_bytes"] = ib
    args["output_bytes"] = ob
    args["work"] = work

    if "deadline_at" in raw and raw["deadline_at"] is not None:
        da = raw["deadline_at"]
        if isinstance(da, bool) or not isinstance(da, (int, float)):
            return ValidationError(tool="submit_job", message="deadline_at must be a number")
        args["deadline_at"] = float(da)
    else:
        off = _float_field(
            "deadline_offset_s",
            DEFAULT_JOB["deadline_offset_s"],
            MIN_DEADLINE_OFFSET,
            MAX_DEADLINE_OFFSET,
        )
        if isinstance(off, ValidationError):
            return off
        args["deadline_offset_s"] = off

    source = str(raw.get("source_id") or DEFAULT_JOB["source_id"])
    dest = str(raw.get("destination_id") or DEFAULT_JOB["destination_id"])
    if catalog.station_ids:
        if source not in catalog.station_ids:
            return ValidationError(tool="submit_job", message=f"unknown source_id: {source}")
        if dest not in catalog.station_ids:
            return ValidationError(tool="submit_job", message=f"unknown destination_id: {dest}")
    args["source_id"] = source
    args["destination_id"] = dest
    return ValidatedAction("submit_job", args)


def _validate_disrupt(raw: dict[str, Any], catalog: WorldCatalog) -> ValidatedAction | ValidationError:
    link_id = raw.get("link_id")
    if not isinstance(link_id, str) or not link_id.strip():
        return ValidationError(tool="disrupt_link", message="link_id is required")
    link_id = link_id.strip()
    if catalog.link_ids and link_id not in catalog.link_ids:
        return ValidationError(tool="disrupt_link", message=f"unknown link_id: {link_id}")

    action = raw.get("action")
    down = raw.get("down")
    if action is None:
        action = "down" if down is not False else "clear"
    action = str(action).lower()
    if action in ("restore", "up", "clear"):
        action = "clear"
    if action in ("drop", "force_down", "down"):
        action = "down"
    if action not in DISRUPT_ACTIONS:
        return ValidationError(tool="disrupt_link", message="action must be down or clear")

    args: dict[str, Any] = {"link_id": link_id, "action": action}
    if "bandwidth_factor" in raw and raw["bandwidth_factor"] is not None:
        bf = raw["bandwidth_factor"]
        if isinstance(bf, bool) or not isinstance(bf, (int, float)):
            return ValidationError(tool="disrupt_link", message="bandwidth_factor must be a number")
        if bf < 0 or bf > 1:
            return ValidationError(tool="disrupt_link", message="bandwidth_factor must be 0–1")
        args["bandwidth_factor"] = float(bf)
    if "until" in raw and raw["until"] is not None:
        until = raw["until"]
        if isinstance(until, bool) or not isinstance(until, (int, float)):
            return ValidationError(tool="disrupt_link", message="until must be a number")
        args["until"] = float(until)
    return ValidatedAction("disrupt_link", args)
