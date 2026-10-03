from app.models.types import LinkKind


def test_terrestrial_always_up(world):
    link = next(L for L in world.links if L.kind == LinkKind.terrestrial)
    assert world.link_up_at(link, 0.0) is True


def test_ground_space_matches_elevation_rule(world):
    gs = world.station_by_id["gs-ashburn"]
    orb = world.node_by_id["orbital-iss-cheap"]
    link = next(
        L
        for L in world.links
        if L.kind == LinkKind.ground_space and {L.endpoint_a, L.endpoint_b} == {gs.id, orb.id}
    )
    # Sample a day; at least one up and one down
    ups = [world.link_up_at(link, t) for t in range(0, 5400, 30)]
    assert any(ups) or any(world.link_up_at(link, t) for t in range(0, 86400, 120))
    downs = [not world.link_up_at(link, t) for t in range(0, 86400, 120)]
    assert any(downs)


def test_disruption_forces_down(world):
    link = next(L for L in world.links if L.kind == LinkKind.terrestrial)
    world.disrupt_link(link.id, down=True)
    assert world.link_up_at(link, world.settings.t) is False
    world.clear_disruption(link.id)
    assert world.link_up_at(link, world.settings.t) is True
