"""Assumption-labelled power and thermal model (not telemetry).

Sun direction is a day-of-year approximation. Eclipse uses a cylindrical
Earth shadow. Battery and thermal states are lumped-parameter toys so the
planner and sim share one deterministic derate.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.orbit.propagate import WGS84_A

LABELS = {
    "sun_model": "approx_ecliptic_doy_not_jpl",
    "eclipse": "cylindrical_earth_shadow",
    "array": "fixed_area_eta_simulated",
    "battery": "lumped_soc_reserve_floor",
    "thermal": "lumped_mass_radiator",
    "source": "labelled_assumption_not_telemetry",
}

# Simulated hardware (labelled)
ARRAY_W_SUNLIT = 1800.0
HOUSEKEEPING_W = 200.0
COMPUTE_W = 800.0
BATTERY_WH = 2400.0
RESERVE_SOC = 0.25
THERMAL_MASS_J_K = 45000.0
RADIATOR_W_K = 12.0
T_SPACE_K = 180.0
T_NOM_K = 293.0
T_WARN_K = 320.0
T_MAX_K = 340.0


class PowerThermalState(BaseModel):
    sunlit: bool
    eclipse: bool
    solar_w: float
    battery_soc: float
    temperature_k: float
    power_factor: float
    thermal_factor: float
    effective_rate_factor: float
    labels: dict[str, str] = Field(default_factory=lambda: dict(LABELS))
    notes: str = "Assumption-labelled model; not spacecraft telemetry."


def sun_ecef_unit(dt: datetime) -> tuple[float, float, float]:
    """Approximate sun direction in ECEF from day-of-year (mean ecliptic)."""
    dt = dt.astimezone(timezone.utc)
    doy = dt.timetuple().tm_yday + (dt.hour + dt.minute / 60.0) / 24.0
    # Mean solar longitude (deg), very rough
    L = math.radians((280.460 + 0.9856474 * doy) % 360.0)
    g = math.radians((357.528 + 0.9856003 * doy) % 360.0)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    ep = math.radians(23.439 - 0.0000004 * doy)
    x = math.cos(lam)
    y = math.cos(ep) * math.sin(lam)
    z = math.sin(ep) * math.sin(lam)
    # Ignore GMST rotation of the sun vector for this labelled toy: treat as inertial-ish
    # in ECEF by applying a Greenwich angle from the same day fraction.
    gst = math.radians((280.16 + 360.9856235 * doy) % 360.0)
    xe = x * math.cos(gst) + y * math.sin(gst)
    ye = -x * math.sin(gst) + y * math.cos(gst)
    n = math.sqrt(xe * xe + ye * ye + z * z) or 1.0
    return xe / n, ye / n, z / n


def in_cylindrical_eclipse(sat_ecef_m: tuple[float, float, float], sun_u: tuple[float, float, float]) -> bool:
    sx, sy, sz = sun_u
    rx, ry, rz = sat_ecef_m
    along = rx * sx + ry * sy + rz * sz
    if along >= 0:
        return False
    px, py, pz = rx - along * sx, ry - along * sy, rz - along * sz
    perp = math.sqrt(px * px + py * py + pz * pz)
    return perp < WGS84_A


class PowerThermalModel:
    """Deterministic derate shared by planner and simulation."""

    def __init__(self):
        self._soc: dict[str, float] = {}
        self._temp: dict[str, float] = {}

    def reset(self) -> None:
        self._soc.clear()
        self._temp.clear()

    def snapshot_earth(self) -> PowerThermalState:
        return PowerThermalState(
            sunlit=True,
            eclipse=False,
            solar_w=0.0,
            battery_soc=1.0,
            temperature_k=T_NOM_K,
            power_factor=1.0,
            thermal_factor=1.0,
            effective_rate_factor=1.0,
            labels={**LABELS, "site": "terrestrial_grid_unlimited"},
            notes="Earth DC assumed on-grid; no eclipse/battery model.",
        )

    def factor_orbital(
        self,
        node_id: str,
        sat_ecef_m: Optional[tuple[float, float, float]],
        dt: datetime,
        computing: bool = False,
        dt_s: float = 5.0,
        mutate: bool = False,
    ) -> PowerThermalState:
        if sat_ecef_m is None:
            st = PowerThermalState(
                sunlit=False,
                eclipse=True,
                solar_w=0.0,
                battery_soc=self._soc.get(node_id, 0.7),
                temperature_k=self._temp.get(node_id, T_NOM_K),
                power_factor=0.0,
                thermal_factor=0.0,
                effective_rate_factor=0.0,
            )
            return st
        sun = sun_ecef_unit(dt)
        eclipse = in_cylindrical_eclipse(sat_ecef_m, sun)
        sunlit = not eclipse
        solar_w = ARRAY_W_SUNLIT if sunlit else 0.0
        load = HOUSEKEEPING_W + (COMPUTE_W if computing else 0.0)
        soc = self._soc.get(node_id, 0.75)
        temp = self._temp.get(node_id, T_NOM_K)
        net_w = solar_w - load
        soc_next = min(1.0, max(0.0, soc + (net_w * dt_s / 3600.0) / BATTERY_WH))
        # Lumped thermal: waste heat from load, radiate to space
        waste = load * 0.7
        cool = RADIATOR_W_K * (temp - T_SPACE_K)
        temp_next = temp + (waste - cool) * dt_s / THERMAL_MASS_J_K
        if mutate:
            self._soc[node_id] = soc_next
            self._temp[node_id] = temp_next
            soc, temp = soc_next, temp_next
        if soc < RESERVE_SOC:
            power_factor = 0.15 if soc > 0.05 else 0.0
        elif not sunlit and soc < RESERVE_SOC + 0.1:
            power_factor = 0.6
        else:
            power_factor = 1.0
        if temp >= T_MAX_K:
            thermal_factor = 0.1
        elif temp >= T_WARN_K:
            thermal_factor = max(0.2, 1.0 - (temp - T_WARN_K) / (T_MAX_K - T_WARN_K))
        else:
            thermal_factor = 1.0
        eff = min(power_factor, thermal_factor)
        return PowerThermalState(
            sunlit=sunlit,
            eclipse=eclipse,
            solar_w=solar_w,
            battery_soc=soc,
            temperature_k=temp,
            power_factor=power_factor,
            thermal_factor=thermal_factor,
            effective_rate_factor=eff,
        )

    def predict_factor(
        self,
        node_id: str,
        sat_ecef_m: Optional[tuple[float, float, float]],
        dt: datetime,
    ) -> float:
        return self.factor_orbital(node_id, sat_ecef_m, dt, computing=True, mutate=False).effective_rate_factor
