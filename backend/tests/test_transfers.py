import pytest

from app.models.types import TransferState


@pytest.mark.asyncio
async def test_transfer_pauses_and_resumes(world):
    await world.reset()
    # Force a terrestrial hop by placing on Earth
    result = await world.submit_job(
        {
            "input_bytes": 2_500_000,
            "output_bytes": 100_000,
            "work": 40.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
            "deadline_at": 10_000,
        }
    )
    assert result.get("plan")
    link_id = result["plan"]["input_route"][0]["link_id"]
    world.disrupt_link(link_id, down=True)
    await world.step()
    paused = [t for t in world.transfers.values() if t.state == TransferState.paused]
    assert paused
    sent = paused[0].bytes_sent
    world.clear_disruption(link_id)
    await world.step()
    nxt = next(t for t in world.transfers.values() if t.id == paused[0].id)
    assert nxt.bytes_sent >= sent
    assert nxt.state in (TransferState.active, TransferState.completed)
