"""Full-horizon visibility matrix vs live geometry and inspector API."""


def test_matrix_matches_geometry(world):
    world.ensure_visibility(0.0, 1800.0)
    assert world.visibility.built
    assert world.visibility.t0 == 0.0
    assert world.visibility.n_steps > 10
    step = world.settings.sim_step_s
    for L in world.links:
        for t in (0.0, 300.0, 900.0, 1500.0):
            cached = world.visibility.up_at(L.id, t, world.settings.disrupted_links)
            live = world.contact_model.link_up_at(L, t, world.settings.disrupted_links)
            assert cached == live, (L.id, t, cached, live)
        # quantized lookup equals geometry at the grid point
        assert world.visibility.geometry_up_at(L.id, 3 * step) == world.contact_model.geometry_up(L, 3 * step)


def test_windows_merge_contiguous(world):
    world.ensure_visibility(0.0, 3600.0)
    terrestrial = [L for L in world.links if L.kind.value == "terrestrial"]
    assert terrestrial
    wins = world.visibility.windows(0.0, 3600.0, links=terrestrial[:1])
    assert len(wins) == 1
    assert wins[0].start == 0.0
    assert wins[0].end >= 3600.0 - 1e-6


def test_disruption_overlay_does_not_rebuild_geometry(world):
    world.ensure_visibility(0.0, 600.0)
    n0 = world.visibility.n_steps
    link_id = world.links[0].id
    world.settings.disrupted_links[link_id] = {"down": True, "until": 400.0}
    assert world.visibility.up_at(link_id, 100.0, world.settings.disrupted_links) is False
    assert world.visibility.n_steps == n0
    world.settings.disrupted_links.clear()
    assert world.visibility.up_at(link_id, 100.0, world.settings.disrupted_links) == world.visibility.geometry_up_at(
        link_id, 100.0
    )


def test_inspector_payload(world):
    body = world.contacts_inspector(horizon_s=600.0)
    assert body["grid"] == "sim_step_from_epoch"
    assert body["t0"] == 0.0
    assert body["t1"] == 600.0
    assert len(body["links"]) == len(world.links)
    assert {row["link_id"] for row in body["links"]} == {L.id for L in world.links}
