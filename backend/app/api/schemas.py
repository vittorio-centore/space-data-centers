"""Request models with bounds."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class JobSubmit(BaseModel):
    input_bytes: int = Field(default=5_000_000, ge=1, le=50_000_000_000)
    output_bytes: int = Field(default=1_000_000, ge=1, le=50_000_000_000)
    work: float = Field(default=200.0, gt=0, le=1_000_000)
    deadline_at: Optional[float] = Field(default=None, ge=0)
    source_id: str = Field(default="gs-ashburn", min_length=1, max_length=64)
    destination_id: str = Field(default="gs-ashburn", min_length=1, max_length=64)
    preset: Optional[str] = Field(default=None, max_length=64)
    policy: str = Field(default="planner", pattern="^(planner|cheapest|earliest|earth_only|round_robin)$")
    forced_node_id: Optional[str] = Field(default=None, max_length=64)
    name: Optional[str] = Field(default=None, max_length=128)


class JobBatchSubmit(BaseModel):
    jobs: list[JobSubmit] = Field(min_length=1, max_length=64)
    policy: str = Field(default="planner", pattern="^(planner|cheapest|earliest|earth_only|round_robin)$")


class SettingsPatch(BaseModel):
    sim_step_s: Optional[float] = Field(default=None, gt=0.1, le=60)
    plan_horizon_s: Optional[float] = Field(default=None, ge=60, le=86400)
    speed: Optional[float] = Field(default=None, gt=0, le=1000)


class DisruptBody(BaseModel):
    down: bool = True
    bandwidth_factor: Optional[float] = Field(default=None, ge=0, le=1)
    until: Optional[float] = Field(default=None, ge=0)


class SeekBody(BaseModel):
    t: float = Field(ge=0, le=10_000_000)


class OutageBody(BaseModel):
    down: bool = True
    until: Optional[float] = Field(default=None, ge=0)
    reason: str = Field(default="injected", max_length=128)


class ScenarioBody(BaseModel):
    id: str = Field(min_length=1, max_length=64)


class EvaluationBody(BaseModel):
    seed: int = Field(default=1, ge=0, le=1_000_000)
    n_jobs: int = Field(default=6, ge=1, le=32)
    policies: Optional[list[str]] = None
    max_steps: int = Field(default=2500, ge=10, le=20_000)


class MarketDayBody(BaseModel):
    seed: int = Field(default=11, ge=0, le=1_000_000)
    n_per_tenant: int = Field(default=5, ge=1, le=16)
    max_steps: int = Field(default=2500, ge=10, le=20_000)


class FilePutBody(BaseModel):
    path: str = Field(min_length=1, max_length=256)
    content: str = Field(default="", max_length=1_000_000)
    content_type: str = Field(default="text/plain", max_length=128)
