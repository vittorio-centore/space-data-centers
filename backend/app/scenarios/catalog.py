"""Named topologies. mvp-thesis is the Case A/B gate."""

from __future__ import annotations

from typing import Any

from app.models.types import ComputeNode, GroundStation, NodeKind
from app.orbit.propagate import OrbitEngine, load_tle_file
from app.topology import (
    DATA_DIR,
    EARTH_NODE,
    GS_ASHBURN,
    GS_MADRID,
    TLE_CACHE,
    build_links,
    build_orbital_nodes,
    default_epoch,
    load_orbital_records,
)

GS_SVALBARD = GroundStation(
    id="gs-svalbard",
    name="Svalbard Gateway",
    lat=78.2297,
    lon=15.4078,
    alt_m=50.0,
    min_elevation_deg=8.0,
    max_range_km=2800.0,
)
GS_SINGAPORE = GroundStation(
    id="gs-singapore",
    name="Singapore Gateway",
    lat=1.3521,
    lon=103.8198,
    alt_m=15.0,
    min_elevation_deg=10.0,
    max_range_km=2500.0,
)
GS_SANTIAGO = GroundStation(
    id="gs-santiago",
    name="Santiago Gateway",
    lat=-33.4489,
    lon=-70.6693,
    alt_m=570.0,
    min_elevation_deg=10.0,
    max_range_km=2500.0,
)
GS_PERTH = GroundStation(
    id="gs-perth",
    name="Perth Gateway",
    lat=-31.9505,
    lon=115.8605,
    alt_m=20.0,
    min_elevation_deg=10.0,
    max_range_km=2500.0,
)

EARTH_EU = ComputeNode(
    id="earth-eu-west",
    kind=NodeKind.earth,
    name="EU-West Terrestrial DC",
    lat=53.35,
    lon=-6.26,
    alt_km=0.05,
    compute_rate=48.0,
    price_per_work=0.022,
    reality_flags={
        "compute_rate": "simulated",
        "price_per_work": "simulated",
        "position": "configured",
        "power_thermal": "labelled_assumption_not_telemetry",
    },
)

SCENARIOS = {
    "mvp-thesis": {
        "id": "mvp-thesis",
        "label": "MVP thesis (1 Earth / 2 GS / 3 orbitals)",
        "description": "Fixed inventory for Case A/B. Do not change node ids.",
    },
    "leo-constellation": {
        "id": "leo-constellation",
        "label": "LEO constellation (2 Earth / 6 GS / extra TLE nodes)",
        "description": "Larger labelled demo; Case A/B are validated on mvp-thesis.",
    },
}


def list_scenarios() -> list[dict[str, str]]:
    return [dict(v) for v in SCENARIOS.values()]


def _constellation_records():
    extra = DATA_DIR / "leo_constellation.tle"
    recs = load_orbital_records()
    if extra.exists():
        more = load_tle_file(extra, source=f"file:{extra.name}")
        by = {r.norad_id: r for r in recs}
        for r in more:
            by[r.norad_id] = r
        recs = list(by.values())
    recs.sort(key=lambda r: r.norad_id)
    return recs


def _orbital_from_records(records) -> list[ComputeNode]:
    # Keep thesis three with stable ids; extras get orbital-{norad}
    base = build_orbital_nodes(records)
    have = {n.orbital_record_id for n in base}
    prices = [0.006, 0.008, 0.009, 0.011, 0.013, 0.007, 0.014, 0.015, 0.016, 0.018, 0.005]
    rates = [38.0, 42.0, 36.0, 40.0, 33.0, 44.0, 37.0, 39.0, 41.0, 34.0, 43.0]
    extras: list[ComputeNode] = []
    i = 0
    for rec in records:
        if rec.id in have:
            continue
        extras.append(
            ComputeNode(
                id=f"orbital-{rec.norad_id}",
                kind=NodeKind.orbital,
                name=f"Orbital {rec.name}",
                orbital_record_id=rec.id,
                compute_rate=rates[i % len(rates)],
                price_per_work=prices[i % len(prices)],
                reality_flags={
                    "compute_rate": "simulated",
                    "price_per_work": "simulated",
                    "position": "derived_from_real_tle",
                    "ephemeris": "real",
                    "power_thermal": "labelled_assumption_not_telemetry",
                },
            )
        )
        i += 1
    extras.sort(key=lambda n: n.id)
    return base + extras


def build_scenario(name: str = "mvp-thesis") -> dict[str, Any]:
    name = name or "mvp-thesis"
    if name not in SCENARIOS:
        name = "mvp-thesis"
    if name == "mvp-thesis":
        records = load_orbital_records()
        epoch = default_epoch()
        orbitals = build_orbital_nodes(records)
        stations = [GS_ASHBURN, GS_MADRID]
        earths = [EARTH_NODE.model_copy()]
        links = build_links(earths[0], stations, orbitals)
        engine = OrbitEngine(records, epoch)
        return {
            "scenario_id": name,
            "records": records,
            "epoch": epoch,
            "earth": earths[0],
            "orbitals": orbitals,
            "stations": stations,
            "nodes": earths + orbitals,
            "links": links,
            "orbit_engine": engine,
        }

    records = _constellation_records()
    epochs = []
    from datetime import datetime, timezone

    for r in records:
        epochs.append(datetime.fromisoformat(r.epoch.replace("Z", "+00:00")))
    epoch = max(epochs).astimezone(timezone.utc)
    orbitals = _orbital_from_records(records)
    stations = [GS_ASHBURN, GS_MADRID, GS_SVALBARD, GS_SINGAPORE, GS_SANTIAGO, GS_PERTH]
    earths = [EARTH_NODE.model_copy(), EARTH_EU.model_copy()]
    links = build_links(earths[0], stations, orbitals)
    # terrestrial from second DC to each GS
    extra = build_links(earths[1], stations, [])
    # drop leftover ISL-less empty: build_links with no orbitals only makes terrestrial
    links = links + extra
    from app.models.types import LinkConfig, LinkKind
    from app.topology import BW_TERRESTRIAL, PRICE_BIT_TERRESTRIAL

    links.append(
        LinkConfig(
            id=f"link-{earths[0].id}-{earths[1].id}",
            kind=LinkKind.terrestrial,
            endpoint_a=earths[0].id,
            endpoint_b=earths[1].id,
            bandwidth_bps=BW_TERRESTRIAL,
            price_per_bit=PRICE_BIT_TERRESTRIAL,
            latency_s=0.03,
            rules={"always_on": True},
            up=True,
        )
    )
    engine = OrbitEngine(records, epoch)
    return {
        "scenario_id": name,
        "records": records,
        "epoch": epoch,
        "earth": earths[0],
        "orbitals": orbitals,
        "stations": stations,
        "nodes": earths + orbitals,
        "links": links,
        "orbit_engine": engine,
    }
