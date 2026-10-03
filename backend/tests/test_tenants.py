import pytest

from app.config import AppConfig
from app.eval.market_day import count_stolen_windows, run_market_day
from app.sim.world import SimWorld
from app.tenants import DEFAULT_TENANT_ID


def _job(name: str, tenant: str, **extra):
    body = {
        "name": name,
        "tenant_id": tenant,
        "input_bytes": 400_000,
        "output_bytes": 80_000,
        "work": 20.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "forced_node_id": "earth-us-east",
        "deadline_at": 50_000,
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_isolation_list_write_collision(world):
    a = await world.submit_job(_job("probe", "alpha"))
    b = await world.submit_job(_job("probe", "beta"))
    assert a["job"]["id"] != b["job"]["id"]
    assert a["job"]["name"] == b["job"]["name"] == "probe"
    assert {j.id for j in world.jobs_for("alpha")} == {a["job"]["id"]}
    assert {j.id for j in world.jobs_for("beta")} == {b["job"]["id"]}
    assert world.get_job(b["job"]["id"], "alpha") is None
    assert world.get_job(a["job"]["id"], "beta") is None

    world.put_file("alpha", "workloads/probe.bin", b"alpha-bytes")
    world.put_file("beta", "workloads/probe.bin", b"beta-bytes")
    assert world.get_file("alpha", "workloads/probe.bin").nbytes == len(b"alpha-bytes")
    assert world.get_file("beta", "workloads/probe.bin").nbytes == len(b"beta-bytes")
    assert world.get_file("alpha", "workloads/probe.bin").content_b64 != world.get_file(
        "beta", "workloads/probe.bin"
    ).content_b64


@pytest.mark.asyncio
async def test_default_open_cannot_smash_seeded_tenant(world):
    seeded = await world.submit_job(_job("owned", "beta"))
    local = await world.submit_job(_job("owned", DEFAULT_TENANT_ID))
    assert seeded["job"]["id"] != local["job"]["id"]
    assert world.get_job(seeded["job"]["id"], DEFAULT_TENANT_ID) is None
    listed_ids = {j.id for j in world.jobs_for(DEFAULT_TENANT_ID)}
    assert seeded["job"]["id"] not in listed_ids
    await world.cancel_job(seeded["job"]["id"])
    # cancel is world-internal; API layer 404s. Job still belongs to beta.
    assert world.jobs[seeded["job"]["id"]].tenant_id == "beta"


@pytest.mark.asyncio
async def test_quota_outstanding_jobs(world):
    world.tenants["alpha"].quota_outstanding_jobs = 1
    ok = await world.submit_job(_job("one", "alpha"))
    assert ok["plan"] is not None
    blocked = await world.submit_job(_job("two", "alpha"))
    assert blocked["code"] == "quota_exceeded"
    assert blocked["plan"] is None
    other = await world.submit_job(_job("beta-ok", "beta"))
    assert other["plan"] is not None


@pytest.mark.asyncio
async def test_exclusive_reservations_across_tenants(world):
    a = await world.submit_job(_job("a-earth", "alpha", work=400.0))
    b = await world.submit_job(_job("b-earth", "beta", work=400.0))
    pa, pb = a["plan"], b["plan"]
    assert pa["compute_node_id"] == pb["compute_node_id"] == "earth-us-east"
    assert pb["compute_start"] + 1e-6 >= pa["compute_end"]
    assert count_stolen_windows(world.reservations, world.link_reservations) == 0


@pytest.mark.asyncio
async def test_crash_restore_keeps_tenant_reservation(tmp_path):
    db = tmp_path / "tenants.sqlite"
    cfg = AppConfig(db_path=db, persist=True, headless=True, scenario="mvp-thesis", log_json=False)
    w1 = SimWorld(cfg, restore=False)
    res = await w1.submit_job(
        {
            "name": "iss-hold",
            "tenant_id": "alpha",
            "input_bytes": 400_000,
            "output_bytes": 80_000,
            "work": 80.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "orbital-iss-cheap",
            "deadline_at": 80_000,
        }
    )
    assert res["plan"] is not None
    job_id = res["job"]["id"]
    start = res["plan"]["compute_start"]
    end = res["plan"]["compute_end"]
    w1.close()

    w2 = SimWorld(cfg, restore=True)
    assert job_id in w2.jobs
    assert w2.jobs[job_id].tenant_id == "alpha"
    assert any(r.job_id == job_id and r.tenant_id == "alpha" for r in w2.reservations)
    steal = await w2.submit_job(
        {
            "name": "iss-want",
            "tenant_id": "beta",
            "input_bytes": 400_000,
            "output_bytes": 80_000,
            "work": 80.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "orbital-iss-cheap",
            "deadline_at": 80_000,
        }
    )
    if steal.get("plan"):
        assert steal["plan"]["compute_start"] + 1e-6 >= end
        assert not (steal["plan"]["compute_start"] < end and start < steal["plan"]["compute_end"])
    assert count_stolen_windows(w2.reservations, w2.link_reservations) == 0
    w2.close()


@pytest.mark.asyncio
async def test_case_a_b_per_tenant(world):
    for tenant in ("alpha", "beta"):
        a = await world.submit_thesis("a", tenant_id=tenant, reset=True)
        assert a["plan"]["compute_node_id"] == "earth-us-east"
        reasons = a["plan"]["baseline_comparison"]["reason_codes"]
        assert "baseline_misses_deadline" in reasons or "chose_non_cheapest" in reasons
        assert a["job"]["tenant_id"] == tenant

        b = await world.submit_thesis("b", tenant_id=tenant, reset=True)
        assert b["plan"]["compute_node_id"] == "orbital-iss-cheap"
        assert "chose_cheapest_node" in b["plan"]["baseline_comparison"]["reason_codes"]
        assert b["job"]["tenant_id"] == tenant


@pytest.mark.asyncio
async def test_crosstalk_unrelated_reservation_does_not_flip_case_a(world):
    await world.reset()
    parked = await world.submit_job(
        {
            "name": "park",
            "tenant_id": "beta",
            "input_bytes": 200_000,
            "output_bytes": 40_000,
            "work": 15.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "orbital-css",
            "deadline_at": 80_000,
        }
    )
    assert parked["plan"] is not None
    a = await world.submit_thesis("a", tenant_id="alpha", reset=False)
    assert a["plan"]["compute_node_id"] == "earth-us-east"
    assert any(r.tenant_id == "beta" for r in world.reservations)


@pytest.mark.asyncio
async def test_market_day_metrics(world):
    report = await run_market_day(world, seed=11, n_per_tenant=3, max_steps=800)
    assert report.stolen_windows == 0
    assert "alpha" in report.deadline_hit_rate
    assert "beta" in report.deadline_hit_rate
    assert report.cost_reservation_aware >= 0
    assert report.cost_global_cheapest_ignores_tenants >= 0
    assert 0.0 <= report.deadline_hit_rate_ignores_tenants <= 1.0
    again = await run_market_day(world, seed=11, n_per_tenant=3, max_steps=800)
    assert again.deadline_hit_rate == report.deadline_hit_rate
    assert again.cost_reservation_aware == report.cost_reservation_aware
    assert again.cost_global_cheapest_ignores_tenants == report.cost_global_cheapest_ignores_tenants
