"""Fixed MVP topology: 1 Earth, 2 GS, 3 orbital compute, links."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.models.types import ComputeNode, GroundStation, LinkConfig, LinkKind, NodeKind, OrbitalRecord
from app.orbit.propagate import OrbitEngine, fetch_or_use_cached

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tles"
TLE_CACHE = DATA_DIR / "leo_compute.tle"

# Ground stations: CONUS-ish (Virginia) and Europe-ish (Madrid)
GS_ASHBURN = GroundStation(
    id="gs-ashburn",
    name="Ashburn Gateway (CONUS)",
    lat=39.0438,
    lon=-77.4874,
    alt_m=80.0,
    min_elevation_deg=10.0,
    max_range_km=2500.0,
)
GS_MADRID = GroundStation(
    id="gs-madrid",
    name="Madrid Gateway (EU)",
    lat=40.4168,
    lon=-3.7038,
    alt_m=650.0,
    min_elevation_deg=10.0,
    max_range_km=2500.0,
)

# Simulated economics tuned for thesis:
# orbital-cheap is cheapest compute but depends on contact windows.
EARTH_NODE = ComputeNode(
    id="earth-us-east",
    kind=NodeKind.earth,
    name="US-East Terrestrial DC",
    lat=39.0,
    lon=-77.5,
    alt_km=0.05,
    compute_rate=50.0,  # work/s — calibrated ~worker wall time
    price_per_work=0.020,
    reality_flags={
        "compute_rate": "simulated",
        "price_per_work": "simulated",
        "position": "configured",
    },
)

# Bandwidth (simulated)
BW_TERRESTRIAL = 100e6  # 100 Mbps
BW_GROUND_SPACE = 20e6  # 20 Mbps
BW_ISL = 50e6  # 50 Mbps
ISL_MAX_RANGE_KM = 4000.0

PRICE_BIT_TERRESTRIAL = 1e-12
PRICE_BIT_GS = 5e-12
PRICE_BIT_ISL = 2e-12


def load_orbital_records() -> list[OrbitalRecord]:
    return fetch_or_use_cached(TLE_CACHE)


def build_orbital_nodes(records: list[OrbitalRecord]) -> list[ComputeNode]:
    """Map 3 TLEs → orbital compute with distinct pricing for thesis."""
    # Sort for stable assignment: ISS cheap, CSS mid, NOAA polar mid-expensive
    by_norad = {r.norad_id: r for r in records}
    specs = [
        ("25544", "orbital-iss-cheap", "Orbital Node ISS (cheap)", 40.0, 0.004),
        ("48274", "orbital-css", "Orbital Node CSS", 45.0, 0.010),
        ("43013", "orbital-noaa", "Orbital Node NOAA-20", 35.0, 0.012),
    ]
    nodes: list[ComputeNode] = []
    for norad, nid, name, rate, price in specs:
        rec = by_norad.get(norad)
        if rec is None:
            # fallback by order
            rec = records[len(nodes)]
        nodes.append(
            ComputeNode(
                id=nid,
                kind=NodeKind.orbital,
                name=name,
                orbital_record_id=rec.id,
                compute_rate=rate,
                price_per_work=price,
                reality_flags={
                    "compute_rate": "simulated",
                    "price_per_work": "simulated",
                    "position": "derived_from_real_tle",
                    "ephemeris": "real",
                },
            )
        )
    return nodes


def build_links(earth: ComputeNode, stations: list[GroundStation], orbitals: list[ComputeNode]) -> list[LinkConfig]:
    links: list[LinkConfig] = []
    # Terrestrial: earth ↔ each GS
    for gs in stations:
        links.append(
            LinkConfig(
                id=f"link-{earth.id}-{gs.id}",
                kind=LinkKind.terrestrial,
                endpoint_a=earth.id,
                endpoint_b=gs.id,
                bandwidth_bps=BW_TERRESTRIAL,
                price_per_bit=PRICE_BIT_TERRESTRIAL,
                latency_s=0.02,
                rules={"always_on": True},
                up=True,
            )
        )
    # Ground-space: each GS ↔ each orbital
    for gs in stations:
        for orb in orbitals:
            links.append(
                LinkConfig(
                    id=f"link-{gs.id}-{orb.id}",
                    kind=LinkKind.ground_space,
                    endpoint_a=gs.id,
                    endpoint_b=orb.id,
                    bandwidth_bps=BW_GROUND_SPACE,
                    price_per_bit=PRICE_BIT_GS,
                    latency_s=0.005,
                    rules={
                        "min_elevation_deg": gs.min_elevation_deg,
                        "max_range_km": gs.max_range_km,
                        "contact": "computed_from_real_sgp4",
                    },
                )
            )
    # ISL between orbitals (range-limited, simulated bandwidth)
    for i, a in enumerate(orbitals):
        for b in orbitals[i + 1 :]:
            links.append(
                LinkConfig(
                    id=f"link-{a.id}-{b.id}",
                    kind=LinkKind.isl,
                    endpoint_a=a.id,
                    endpoint_b=b.id,
                    bandwidth_bps=BW_ISL,
                    price_per_bit=PRICE_BIT_ISL,
                    latency_s=0.002,
                    rules={"max_range_km": ISL_MAX_RANGE_KM, "presence": "simulated"},
                )
            )
    return links


def default_epoch() -> datetime:
    """Sim epoch = latest TLE epoch (UTC) so propagation is near epoch."""
    records = load_orbital_records()
    epochs = [datetime.fromisoformat(r.epoch.replace("Z", "+00:00")) for r in records]
    return max(epochs).astimezone(timezone.utc)


def build_topology():
    records = load_orbital_records()
    epoch = default_epoch()
    orbitals = build_orbital_nodes(records)
    stations = [GS_ASHBURN, GS_MADRID]
    earth = EARTH_NODE.model_copy()
    links = build_links(earth, stations, orbitals)
    engine = OrbitEngine(records, epoch)
    return {
        "records": records,
        "epoch": epoch,
        "earth": earth,
        "orbitals": orbitals,
        "stations": stations,
        "nodes": [earth] + orbitals,
        "links": links,
        "orbit_engine": engine,
    }
