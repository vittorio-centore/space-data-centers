from app.config import AppConfig
from app.instance import InstanceGuard
from app.sim.world import SimWorld


def test_instance_guard_exclusive(tmp_path):
    db = tmp_path / "sdc.sqlite"
    a = InstanceGuard(db)
    b = InstanceGuard(db)
    assert a.acquire() is True
    assert b.acquire() is False
    a.release()
    assert b.acquire() is True
    b.release()


def test_second_world_blocked_from_wal(tmp_path):
    db = tmp_path / "owned.sqlite"
    cfg_a = AppConfig(db_path=db, persist=True, instance_lock=True, headless=True, scenario="mvp-thesis", log_json=False)
    cfg_b = AppConfig(db_path=db, persist=True, instance_lock=True, headless=True, scenario="mvp-thesis", log_json=False)
    a = SimWorld(cfg_a, restore=False)
    assert a.store is not None
    assert a.ready()["ok"] is True
    b = SimWorld(cfg_b, restore=False)
    assert b.store is None
    ready = b.ready()
    assert ready["ok"] is False
    assert ready["error"] and "instance_lock" in ready["error"]
    a.instance.release()
