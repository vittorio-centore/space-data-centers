import pytest


@pytest.mark.asyncio
async def test_compute_reservation_serializes_same_node(world):
    body = {
        "input_bytes": 200_000,
        "output_bytes": 50_000,
        "work": 400.0,
        "source_id": "gs-ashburn",
        "destination_id": "gs-ashburn",
        "forced_node_id": "earth-us-east",
        "deadline_at": 50_000,
    }
    a = await world.submit_job(body)
    b = await world.submit_job(body)
    pa, pb = a["plan"], b["plan"]
    assert pa["compute_node_id"] == pb["compute_node_id"] == "earth-us-east"
    # second slot starts at/after first ends
    assert pb["compute_start"] + 1e-6 >= pa["compute_end"]


@pytest.mark.asyncio
async def test_link_reservations_recorded(world):
    r = await world.submit_job(
        {
            "input_bytes": 800_000,
            "output_bytes": 100_000,
            "work": 20.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
        }
    )
    assert r["plan"]["input_route"]
    assert any(lr.link_id for lr in world.link_reservations)
