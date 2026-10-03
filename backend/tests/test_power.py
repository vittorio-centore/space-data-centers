from app.physics.power_thermal import LABELS, PowerThermalModel, in_cylindrical_eclipse, sun_ecef_unit
from datetime import datetime, timezone


def test_sun_unit_normalized():
    u = sun_ecef_unit(datetime(2026, 10, 3, tzinfo=timezone.utc))
    n = (u[0] ** 2 + u[1] ** 2 + u[2] ** 2) ** 0.5
    assert abs(n - 1.0) < 1e-6


def test_eclipse_behind_earth():
    sun = (1.0, 0.0, 0.0)
    sat = (-8.0e6, 0.0, 0.0)
    assert in_cylindrical_eclipse(sat, sun)
    assert not in_cylindrical_eclipse((8.0e6, 0.0, 0.0), sun)


def test_earth_node_factor_one(world):
    n = world.node_by_id["earth-us-east"]
    assert world._rate_factor(n, 0.0) == 1.0
    assert n.power_thermal is None or n.power_thermal.get("effective_rate_factor") == 1.0
    world._refresh_power(mutate=False)
    assert world.node_by_id["earth-us-east"].power_thermal["labels"]["source"] == "labelled_assumption_not_telemetry"


def test_orbital_state_labelled(world):
    world._refresh_power(mutate=False)
    pt = world.node_by_id["orbital-iss-cheap"].power_thermal
    assert "sunlit" in pt
    assert pt["labels"]["eclipse"] == "cylindrical_earth_shadow"
    m = PowerThermalModel()
    assert 0.0 <= m.predict_factor("x", (7e6, 0, 0), world.orbit.datetime_at(0)) <= 1.0
    for key, value in LABELS.items():
        assert pt["labels"][key] == value
    assert "not spacecraft telemetry" in (pt.get("notes") or "").lower() or "labelled" in pt["labels"]["source"]
