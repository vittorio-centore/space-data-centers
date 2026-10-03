"""Per-tenant work, reserved-seconds, and outstanding-job quotas."""

import pytest


def _job(tenant, **extra):
    body = {
        "tenant_id": tenant,
        "input_bytes": 300_000,
        "output_bytes": 60_000,
        "work": 40.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "forced_node_id": "earth-us-east",
        "deadline_at": 50_000,
    }
    body.update(extra)
    return body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quota_work_blocks_only_that_tenant(world):
    world.tenants["alpha"].quota_work = 30.0
    blocked = await world.submit_job(_job("alpha", work=80.0))
    assert blocked.get("code") == "quota_exceeded"
    ok = await world.submit_job(_job("beta", work=80.0))
    assert ok.get("plan") is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quota_reserved_seconds(world):
    world.tenants["alpha"].quota_reserved_s = 0.01
    r = await world.submit_job(_job("alpha", work=400.0))
    assert r.get("plan") is None
    assert r.get("code") == "quota_exceeded"
    snap = world.quota_snapshot("alpha")
    assert snap["quota_reserved_s"] == 0.01
    assert snap["outstanding_jobs"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quota_snapshot_after_accept(world):
    r = await world.submit_job(_job("alpha", work=25.0))
    assert r.get("plan")
    snap = world.quota_snapshot("alpha")
    assert snap["outstanding_jobs"] >= 1
    assert snap["reserved_s"] > 0
    assert snap["outstanding_work"] > 0
