"""Core data models. Units: seconds, meters, bytes, B/s (where noted), dollars."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    earth = "earth"
    orbital = "orbital"


class LinkKind(str, Enum):
    ground_space = "ground_space"
    isl = "isl"
    terrestrial = "terrestrial"


class JobState(str, Enum):
    submitted = "submitted"
    planned = "planned"
    input_transfer = "input_transfer"
    queued = "queued"
    running = "running"
    output_transfer = "output_transfer"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class TransferDirection(str, Enum):
    input = "input"
    output = "output"


class TransferState(str, Enum):
    pending = "pending"
    active = "active"
    paused = "paused"
    completed = "completed"
    failed = "failed"


class OrbitalRecord(BaseModel):
    id: str
    source: str
    tle_line1: str
    tle_line2: str
    name: str
    epoch: str  # ISO-8601 UTC
    norad_id: str
    reality: Literal["real"] = "real"


class ComputeNode(BaseModel):
    id: str
    kind: NodeKind
    name: str
    orbital_record_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_km: Optional[float] = None
    compute_rate: float  # work units / s (sim)
    price_per_work: float  # dollars per work unit (simulated)
    available_at: float = 0.0
    slots: int = 1
    position_eci_m: Optional[list[float]] = None
    position_lla: Optional[dict[str, float]] = None
    power_thermal: Optional[dict[str, Any]] = None
    reality_flags: dict[str, str] = Field(
        default_factory=lambda: {
            "compute_rate": "simulated",
            "price_per_work": "simulated",
            "position": "derived_from_real_tle" if True else "configured",
            "power_thermal": "labelled_assumption_not_telemetry",
        }
    )


class GroundStation(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    alt_m: float
    min_elevation_deg: float = 10.0
    max_range_km: Optional[float] = 2500.0
    reality: Literal["configured"] = "configured"


class LinkConfig(BaseModel):
    id: str
    kind: LinkKind
    endpoint_a: str
    endpoint_b: str
    bandwidth_bps: float  # simulated bit/s when up
    price_per_bit: float  # simulated $/bit
    latency_s: float = 0.0
    rules: dict[str, Any] = Field(default_factory=dict)
    up: bool = False
    reality: Literal["simulated_bandwidth_pricing"] = "simulated_bandwidth_pricing"


class Hop(BaseModel):
    from_id: str
    to_id: str
    link_id: Optional[str] = None
    window_start: float
    window_end: float
    bytes: int


class BaselineComparison(BaseModel):
    baseline_node_id: str
    baseline_cost: float
    baseline_completion: float
    baseline_feasible: bool
    chosen_node_id: str
    chosen_cost: float
    chosen_completion: float
    reason_codes: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    id: str
    job_id: str
    compute_node_id: str
    input_route: list[Hop]
    output_route: list[Hop]
    compute_start: float
    compute_end: float
    estimated_cost: float
    estimated_completion: float
    baseline_comparison: Optional[BaselineComparison] = None
    transfer_cost: float = 0.0
    compute_cost: float = 0.0
    revision: int = 1
    parent_plan_id: Optional[str] = None
    migrated_from_node_id: Optional[str] = None
    policy: str = "planner"
    rate_factor: float = 1.0


class Job(BaseModel):
    id: str
    submitted_at: float
    input_bytes: int
    output_bytes: int
    work: float
    deadline_at: Optional[float] = None
    source_id: str
    destination_id: str
    state: JobState = JobState.submitted
    assigned_node_id: Optional[str] = None
    plan_id: Optional[str] = None
    fail_reason: Optional[str] = None
    actual_completion: Optional[float] = None
    actual_cost: Optional[float] = None
    worker_started: bool = False
    worker_done: bool = False
    worker_error: Optional[str] = None
    preset: Optional[str] = None
    data_location_id: Optional[str] = None
    policy: str = "planner"
    scenario_id: Optional[str] = None
    seq: int = 0


class Transfer(BaseModel):
    id: str
    job_id: str
    direction: TransferDirection
    from_id: str
    to_id: str
    bytes_total: int
    bytes_sent: int = 0
    state: TransferState = TransferState.pending
    active_link_id: Optional[str] = None
    hop_index: int = 0


class Event(BaseModel):
    id: str
    t: float
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    seq: int = 0


class Settings(BaseModel):
    sim_step_s: float = 5.0
    plan_horizon_s: float = 7200.0
    epoch_utc: str = ""
    playing: bool = False
    speed: float = 1.0  # wall-clock multiplier for tick scheduling
    t: float = 0.0
    disrupted_links: dict[str, dict[str, Any]] = Field(default_factory=dict)
    scenario_id: str = "mvp-thesis"
    headless: bool = False
    persist: bool = True
    tick_errors: int = 0


class WorkerStatus(BaseModel):
    id: str
    job_id: Optional[str] = None
    state: str = "idle"
    detail: Optional[str] = None


class Reservation(BaseModel):
    job_id: str
    node_id: str
    start: float
    end: float


class LinkReservation(BaseModel):
    job_id: str
    link_id: str
    start: float
    end: float
    bytes: int = 0


class NodeOutage(BaseModel):
    node_id: str
    until: Optional[float] = None
    reason: str = "injected"
    down: bool = True


class EvaluationPolicyRow(BaseModel):
    policy: str
    n_jobs: int
    deadline_hit_rate: float
    mean_cost: float
    mean_completion: float
    mean_compute_wait_s: float
    completion_prediction_mae: float
    cost_prediction_mae: float
    n_failed: int


class EvaluationReport(BaseModel):
    id: str
    scenario_id: str
    seed: int
    created_t: float
    policies: list[EvaluationPolicyRow]
    job_template: dict[str, Any] = Field(default_factory=dict)


# Objective constants (documented per spec Appendix A)
OBJECTIVE_PREFER_DEADLINE = True
OBJECTIVE_TIEBREAK = "earlier_completion_then_cost"
