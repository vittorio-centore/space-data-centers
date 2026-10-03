"""Contact evaluation + full-horizon visibility matrix shared by planner, sim, and inspector."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from app.models.types import GroundStation, LinkConfig, LinkKind, NodeKind
from app.orbit.propagate import OrbitEngine, WGS84_A, elevation_deg, geodetic_to_ecef, range_m


def earth_occludes(a: tuple[float, float, float], b: tuple[float, float, float], margin_m: float = 50_000.0) -> bool:
    """True if the segment a–b intersects a sphere of Earth radius + margin (ISL blockage)."""
    ax, ay, az = a
    bx, by, bz = b
    dx, dy, dz = bx - ax, by - ay, bz - az
    t = -(ax * dx + ay * dy + az * dz) / (dx * dx + dy * dy + dz * dz + 1e-12)
    t = max(0.0, min(1.0, t))
    px, py, pz = ax + t * dx, ay + t * dy, az + t * dz
    return math.sqrt(px * px + py * py + pz * pz) < (WGS84_A + margin_m)


def _disrupted_down(disrupted: dict, link_id: str, t: float) -> bool:
    d = disrupted.get(link_id) or {}
    if d.get("down"):
        until = d.get("until")
        if until is None or t < float(until):
            return True
    if float(d.get("bandwidth_factor", 1.0)) <= 0:
        return True
    return False


def _bandwidth_factor(disrupted: dict, link_id: str) -> float:
    d = disrupted.get(link_id) or {}
    return float(d.get("bandwidth_factor", 1.0))


@dataclass
class ContactWindow:
    link_id: str
    a: str
    b: str
    start: float
    end: float
    bandwidth_bps: float
    price_per_bit: float


class ContactModel:
    def __init__(
        self,
        orbit: OrbitEngine,
        stations: dict[str, GroundStation],
        nodes: dict,
        links: list[LinkConfig],
    ):
        self.orbit = orbit
        self.stations = stations
        self.nodes = nodes
        self.links = sorted(links, key=lambda L: L.id)

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

    def geometry_up(self, link: LinkConfig, t: float) -> bool:
        """Link up from geometry + rules only (no injected disruptions)."""
        if link.kind == LinkKind.terrestrial:
            return True
        if link.kind == LinkKind.ground_space:
            gs_id = link.endpoint_a if link.endpoint_a in self.stations else link.endpoint_b
            orb_id = link.endpoint_b if gs_id == link.endpoint_a else link.endpoint_a
            gs = self.stations.get(gs_id)
            orb = self.nodes.get(orb_id)
            if gs is None or orb is None or not getattr(orb, "orbital_record_id", None):
                return False
            ecef = self.orbit.position_ecef_m(orb.orbital_record_id, t)
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
            a = self.nodes.get(link.endpoint_a)
            b = self.nodes.get(link.endpoint_b)
            if not a or not b or a.kind != NodeKind.orbital or b.kind != NodeKind.orbital:
                return False
            if not a.orbital_record_id or not b.orbital_record_id:
                return False
            ea = self.orbit.position_ecef_m(a.orbital_record_id, t)
            eb = self.orbit.position_ecef_m(b.orbital_record_id, t)
            if ea is None or eb is None:
                return False
            max_km = float(link.rules.get("max_range_km", 4000))
            if range_m(ea, eb) > max_km * 1000:
                return False
            return not earth_occludes(ea, eb)
        return False

    def link_up_at(self, link: LinkConfig, t: float, disrupted: Optional[dict] = None) -> bool:
        if disrupted and _disrupted_down(disrupted, link.id, t):
            return False
        return self.geometry_up(link, t)


class VisibilityMatrix:
    """Precomputed full-horizon link-up bitmap on the shared sim_step grid.

    Geometry is computed once and reused by the planner and inspector.
    Injected disruptions are applied at query time so a flap does not rebuild SGP4.
    """

    def __init__(self, model: ContactModel, step_s: float):
        self.model = model
        self.step_s = float(step_s)
        self.t0 = 0.0
        self.t1 = 0.0
        self.n_steps = 0
        self.geom_up: dict[str, list[bool]] = {}
        self.built = False

    def invalidate(self) -> None:
        self.built = False
        self.geom_up = {}
        self.n_steps = 0
        self.t0 = 0.0
        self.t1 = 0.0

    def set_step(self, step_s: float) -> None:
        step_s = float(step_s)
        if abs(step_s - self.step_s) > 1e-12:
            self.step_s = step_s
            self.invalidate()

    def _idx(self, t: float) -> int:
        return int(math.floor(t / self.step_s + 1e-12))

    def ensure(self, t_start: float, t_end: float) -> None:
        """Grow the matrix so [t_start, t_end] is covered on the global grid from 0."""
        step = self.step_s
        need_end = max(0.0, float(t_end))
        if need_end <= 0:
            need_end = step
        if self.built and need_end <= self.t1 + 1e-9 and self.geom_up:
            return
        # Always start at epoch 0 so planner, sim, and inspector share one grid.
        n_steps = int(math.ceil(need_end / step)) + 1
        start_i = self.n_steps if self.built else 0
        if not self.built:
            self.geom_up = {L.id: [] for L in self.model.links}
            self.t0 = 0.0
        for L in self.model.links:
            row = self.geom_up.setdefault(L.id, [])
            if len(row) > start_i:
                row[:] = row[:start_i]
        for i in range(start_i, n_steps):
            t = i * step
            for L in self.model.links:
                self.geom_up[L.id].append(self.model.geometry_up(L, t))
        self.n_steps = n_steps
        self.t1 = (n_steps - 1) * step
        self.built = True

    def geometry_up_at(self, link_id: str, t: float) -> bool:
        if not self.built:
            return False
        i = self._idx(t)
        row = self.geom_up.get(link_id)
        if not row or i < 0 or i >= len(row):
            return False
        return row[i]

    def up_at(self, link_id: str, t: float, disrupted: Optional[dict] = None) -> bool:
        if disrupted and _disrupted_down(disrupted, link_id, t):
            return False
        return self.geometry_up_at(link_id, t)

    def windows(
        self,
        t_start: float,
        t_end: float,
        *,
        disrupted: Optional[dict] = None,
        links: Optional[list[LinkConfig]] = None,
    ) -> list[ContactWindow]:
        self.ensure(t_start, t_end)
        disrupted = disrupted or {}
        step = self.step_s
        i0 = max(0, self._idx(t_start))
        i1 = min(self.n_steps, self._idx(t_end) + 1)
        out: list[ContactWindow] = []
        catalog = links or self.model.links
        for link in catalog:
            row = self.geom_up.get(link.id) or []
            i = i0
            while i < i1:
                t = i * step
                if i >= len(row) or not row[i] or _disrupted_down(disrupted, link.id, t):
                    i += 1
                    continue
                j = i
                while j < i1 and j < len(row) and row[j] and not _disrupted_down(disrupted, link.id, j * step):
                    j += 1
                factor = _bandwidth_factor(disrupted, link.id)
                out.append(
                    ContactWindow(
                        link_id=link.id,
                        a=link.endpoint_a,
                        b=link.endpoint_b,
                        start=max(i * step, t_start),
                        end=min(j * step, t_end),
                        bandwidth_bps=link.bandwidth_bps * factor,
                        price_per_bit=link.price_per_bit,
                    )
                )
                i = j
        out.sort(key=lambda w: (w.start, w.link_id))
        return out

    def inspector_payload(
        self,
        t_now: float,
        horizon_s: float,
        disrupted: Optional[dict] = None,
        up_now: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        t0 = max(0.0, float(t_now))
        t1 = t0 + float(horizon_s)
        self.ensure(t0, t1)
        disrupted = disrupted or {}
        links_out = []
        for link in self.model.links:
            wins = [
                {"start": w.start, "end": w.end, "bandwidth_bps": w.bandwidth_bps}
                for w in self.windows(t0, t1, disrupted=disrupted, links=[link])
            ]
            now = up_now.get(link.id) if up_now is not None else self.up_at(link.id, t0, disrupted)
            links_out.append(
                {
                    "link_id": link.id,
                    "kind": link.kind.value if hasattr(link.kind, "value") else str(link.kind),
                    "a": link.endpoint_a,
                    "b": link.endpoint_b,
                    "up_now": bool(now),
                    "windows": wins,
                }
            )
        return {
            "t0": t0,
            "t1": t1,
            "step_s": self.step_s,
            "n_steps": int(math.ceil((t1 - t0) / self.step_s)) + 1,
            "grid": "sim_step_from_epoch",
            "links": links_out,
        }
