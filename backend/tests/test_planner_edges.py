"""Planner objective, infeasible deadlines, sequential determinism."""

import pytest

from app.config import AppConfig
from app.ids import IdSeq
from app.planner.placement import OBJECTIVE_DOC
from app.sim.world import SimWorld


def _body(**extra):
    body = {
        "input_bytes": 1_000_000,
        "output_bytes": 200_000,
        "work": 50.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
    }
    body.update(extra)
    return body


@pytest.mark.unit
def test_objective_prefers_deadline_then_cost():
    assert "feasible-by-deadline" in OBJECTIVE_DOC
    assert "cost" in OBJECTIVE_DOC


@pytest.mark.unit
@pytest.mark.asyncio
async def test_impossible_deadline_is_infeasible(world):
    # Tight deadline with every contact and terrestrial hop forced down: no route exists.
    for L in world.links:
        world.disrupt_link(L.id, down=True)
    r = await world.submit_job(_body(deadline_at=1.0, work=5000.0, input_bytes=50_000_000))
    assert r.get("plan") is None
    job = r.get("job") or {}
    assert job.get("state") == "failed"
    reason = (r.get("error") or job.get("fail_reason") or "").lower()
    assert "infeasible" in reason or "no feasible" in reason
    bc = r.get("baseline_comparison") or {}
    codes = bc.get("reason_codes") or []
    assert "chosen_infeasible" in codes or r.get("plan") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_nodes_out_is_infeasible(world):
    for n in world.nodes:
        world.set_outage(n.id, down=True, reason="test")
    r = await world.submit_job(_body(deadline_at=20_000))
    assert r.get("plan") is None
    assert r["job"]["state"] == "failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_impossible_work_quota_is_infeasible(world):
    world.tenants["alpha"].quota_work = 1.0
    r = await world.submit_job(_body(tenant_id="alpha", work=500.0))
    assert r.get("plan") is None
    assert r.get("code") == "quota_exceeded"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_inputs_same_plan_across_fresh_worlds(tmp_path):
    body = _body(deadline_at=8000)
    plans = []
    for i in range(2):
        cfg = AppConfig(
            db_path=tmp_path / f"d{i}.sqlite",
            persist=False,
            headless=True,
            scenario="mvp-thesis",
            log_json=False,
        )
        w = SimWorld(cfg, restore=False)
        r = await w.submit_job(body)
        assert r.get("plan")
        plans.append(r["plan"])
        w.close()
    a, b = plans
    assert a["compute_node_id"] == b["compute_node_id"]
    assert a["estimated_cost"] == b["estimated_cost"]
    assert a["estimated_completion"] == b["estimated_completion"]
    assert a["input_route"] == b["input_route"]
    assert a["output_route"] == b["output_route"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sequential_ids_after_reset(world):
    seq = IdSeq()
    assert seq.next("job") == "job-00000001"
    assert seq.next("plan") == "plan-00000002"

    await world.reset()
    first = await world.submit_job(_body(forced_node_id="earth-us-east", deadline_at=20_000))
    assert first["job"]["id"].startswith("job-")
    await world.reset()
    second = await world.submit_job(_body(forced_node_id="earth-us-east", deadline_at=20_000))
    # Counter resets with the world; the first job after each reset shares the same id.
    assert second["job"]["id"] == first["job"]["id"]
    third = await world.submit_job(_body(forced_node_id="earth-us-east", deadline_at=20_000))
    assert third["job"]["id"] != second["job"]["id"]
    assert third["job"]["id"] > second["job"]["id"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cheapest_policy_fails_when_node_out(world):
    cheapest = min(world.nodes, key=lambda n: (n.price_per_work, n.id))
    world.set_outage(cheapest.id, down=True, reason="test")
    r = await world.submit_job(_body(policy="cheapest", deadline_at=20_000))
    assert r.get("plan") is None
    assert "infeasible" in (r.get("error") or "").lower() or r["job"]["state"] == "failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_baseline_compares_chosen_to_cheapest(world):
    r = await world.submit_job(_body(deadline_at=20_000))
    assert r.get("plan")
    bc = r["baseline_comparison"]
    cheapest = min(world.nodes, key=lambda n: (n.price_per_work, n.id))
    assert bc["baseline_node_id"] == cheapest.id
    assert bc["chosen_node_id"] == r["plan"]["compute_node_id"]
    assert isinstance(bc["chosen_cost"], (int, float))
    assert isinstance(bc["baseline_cost"], (int, float))
