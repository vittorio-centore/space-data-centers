import pytest

from app.config import AppConfig
from app.models.types import Job
from app.sim.world import SimWorld


@pytest.mark.asyncio
async def test_sqlite_restore(tmp_path):
    db = tmp_path / "sdc.sqlite"
    cfg = AppConfig(db_path=db, persist=True, headless=True, scenario="mvp-thesis", log_json=False)
    w1 = SimWorld(cfg, restore=False)
    await w1.submit_job(
        {
            "input_bytes": 400_000,
            "output_bytes": 80_000,
            "work": 25.0,
            "source_id": "gs-ashburn",
            "destination_id": "gs-ashburn",
            "forced_node_id": "earth-us-east",
        }
    )
    job_id = next(iter(w1.jobs))
    t = w1.settings.t
    w1.store.set_meta("t", t)
    w1.close()
    w2 = SimWorld(cfg, restore=True)
    assert job_id in w2.jobs
    assert isinstance(w2.jobs[job_id], Job)
    assert w2.jobs[job_id].assigned_node_id == "earth-us-east"
    assert w2.plans
    w2.close()
