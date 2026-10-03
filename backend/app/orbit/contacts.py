"""Contact evaluation + quantized position cache shared by planner and sim."""

from __future__ import annotations

import math
from typing import Optional

from app.models.types import GroundStation, LinkConfig, LinkKind, NodeKind
from app.orbit.propagate import OrbitEngine, WGS84_A, elevation_deg, geodetic_to_ecef, range_m


def earth_occludes(a: tuple[float, float, float], b: tuple[float, float, float], margin_m: float = 50_000.0) -> bool:
    """True if the segment a–b intersects a sphere of Earth radius + margin (ISL blockage)."""
    ax, ay, az = a
    bx, by, bz = b
    dx, dy, dz = bx - ax, by - ay, bz - az
    # Closest point on segment to origin
    t = - (ax * dx + ay * dy + az * dz) / (dx * dx + dy * dy + dz * dz + 1e-12)
    t = max(0.0, min(1.0, t))
    px, py, pz = ax + t * dx, ay + t * dy, az + t * dz
    return math.sqrt(px * px + py * py + pz * pz) < (WGS84_A + margin_m)


class ContactModel:
    def __init__(
        self,
        orbit: OrbitEngine,
        stations: dict[str, GroundStation],
        nodes: dict,
        links: list[LinkConfig],
        disrupted: dict,
        outages: dict,
    ):
        self.orbit = orbit
        self.stations = stations
        self.nodes = nodes
        self.links = links
        self.disrupted = disrupted
        self.outages = outages

    def _disrupted_down(self, link_id: str, t: float) -> bool:
        d = self.disrupted.get(link_id) or {}
        if d.get("down"):
            until = d.get("until")
            if until is None or t < float(until):
                return True
        if float(d.get("bandwidth_factor", 1.0)) <= 0:
            return True
        return False

    def endpoint_ecef(self, eid: str, t: float) -> Optional[tuple[float, float, float]]:
        if eid in self.stations:
            s = self.stations[eid]
            return geodetic_to_ecef(s.lat, s.lon, s.alt_m)
        n = self.nodes.get(eid)
        if not n:
            return None
        if getattr(n, "kind", None) == NodeKind.earth:
            return geodetic_to_ecef(n.lat or 0, n.lon or 0, (n.alt_km or 0) * 1000)
        if n.orbital_record_id:
            return self.orbit.position_ecef_m(n.orbital_record_id, t)
        return None

    def link_up_at(self, link: LinkConfig, t: float) -> bool:
        if self._disrupted_down(link.id, t):
            return False
        # Endpoint compute outages do not drop the radio by themselves
        if link.kind == LinkKind.terrestrial:
            return True
        if link.kind == LinkKind.ground_space:
            gs_id = link.endpoint_a if link.endpoint_a in self.stations else link.endpoint_b
            orb_id = link.endpoint_b if gs_id == link.endpoint_a else link.endpoint_a
            gs = self.stations[gs_id]
            orb = self.nodes[orb_id]
            ecef = self.orbit.position_ecef_m(orb.orbital_record_id, t)  # type: ignore
            if ecef is None:
                return False
            el = elevation_deg(gs.lat, gs.lon, gs.alt_m, ecef)
            min_el = link.rules.get("min_elevation_deg", gs.min_elevation_deg)
            if el < min_el:
                return False
            max_range = link.rules.get("max_range_km", gs.max_range_km)
            if max_range is not None:
                s_ecef = geodetic_to_ecef(gs.lat, gs.lon, gs.alt_m)
                if range_m(s_ecef, ecef) > float(max_range) * 1000:
                    return False
            return True
        if link.kind == LinkKind.isl:
            a = self.nodes[link.endpoint_a]
            b = self.nodes[link.endpoint_b]
            if a.kind != NodeKind.orbital or b.kind != NodeKind.orbital:
                return False
            ea = self.orbit.position_ecef_m(a.orbital_record_id, t)  # type: ignore
            eb = self.orbit.position_ecef_m(b.orbital_record_id, t)  # type: ignore
            if ea is None or eb is None:
                return False
            max_km = float(link.rules.get("max_range_km", 4000))
            if range_m(ea, eb) > max_km * 1000:
                return False
            return not earth_occludes(ea, eb)
        return False
