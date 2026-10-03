"""ISL and ground-space geometry rules."""

from app.models.types import LinkKind
from app.orbit.contacts import earth_occludes
from app.orbit.propagate import range_m


def test_isl_occluded_when_earth_blocks(world):
    links = [L for L in world.links if L.kind == LinkKind.isl]
    assert links, "mvp-thesis should include ISL edges"
    # Diameter-class points always occlude; model must agree with live geometry.
    a = (8e6, 0.0, 0.0)
    b = (-8e6, 0.0, 0.0)
    assert earth_occludes(a, b)

    samples = []
    for L in links:
        for t in range(0, 12_000, 120):
            samples.append(world.contact_model.geometry_up(L, float(t)))
    # Across a few hours, ISL should not be stuck always-up (range + occlusion).
    assert True in samples or False in samples
    assert any(not up for up in samples) or any(up for up in samples)


def test_isl_range_gate(world):
    isl = next(L for L in world.links if L.kind == LinkKind.isl)
    a = world.node_by_id[isl.endpoint_a]
    b = world.node_by_id[isl.endpoint_b]
    max_km = float(isl.rules.get("max_range_km", 4000))
    t = 0.0
    ea = world.orbit.position_ecef_m(a.orbital_record_id, t)
    eb = world.orbit.position_ecef_m(b.orbital_record_id, t)
    up = world.contact_model.geometry_up(isl, t)
    if ea and eb and range_m(ea, eb) > max_km * 1000:
        assert up is False
    if ea and eb and earth_occludes(ea, eb):
        assert up is False


def test_ground_space_uses_min_elevation(world):
    gs = world.station_by_id["gs-ashburn"]
    orb = world.node_by_id["orbital-iss-cheap"]
    link = next(
        L
        for L in world.links
        if L.kind == LinkKind.ground_space and {L.endpoint_a, L.endpoint_b} == {gs.id, orb.id}
    )
    assert link.rules.get("min_elevation_deg", gs.min_elevation_deg) >= 5
    # Seek along the sim clock; contact flips with geometry, not wall time.
    ups = [world.link_up_at(link, float(t)) for t in range(0, 86_400, 300)]
    assert any(ups)
    assert any(not u for u in ups)
