"""SGP4 orbit propagation from real TLEs. Positions derived from real ephemeris."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sgp4.api import Satrec, jday
from sgp4.conveniences import sat_epoch_datetime
from sgp4.propagation import gstime

from app.models.types import OrbitalRecord

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + alt_m) * cos_lat * math.cos(lon)
    y = (n + alt_m) * cos_lat * math.sin(lon)
    z = (n * (1 - WGS84_E2) + alt_m) * sin_lat
    return x, y, z


def eci_to_ecef(x: float, y: float, z: float, dt: datetime) -> tuple[float, float, float]:
    """TEME (SGP4) → ECEF via Vallado GMST from the sgp4 package.

    Rotates TEME km coordinates about Z by Greenwich sidereal time.
    Polar motion / LOD are omitted (sub-km class effect for contact MVP).
    """
    dt = dt.astimezone(timezone.utc)
    jd, fr = jday(
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second + dt.microsecond * 1e-6,
    )
    theta = gstime(jd + fr)  # radians, consistent with SGP4 library
    cos_g = math.cos(theta)
    sin_g = math.sin(theta)
    xe = (x * cos_g + y * sin_g) * 1000.0
    ye = (-x * sin_g + y * cos_g) * 1000.0
    ze = z * 1000.0
    return xe, ye, ze


def ecef_to_lla(x: float, y: float, z: float) -> tuple[float, float, float]:
    lon = math.atan2(y, x)
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1 - WGS84_E2))
    for _ in range(8):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - WGS84_E2 * n / (n + alt)))
    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), alt


def range_m(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def elevation_deg(
    station_lat: float,
    station_lon: float,
    station_alt_m: float,
    sat_ecef_m: tuple[float, float, float],
) -> float:
    sx, sy, sz = geodetic_to_ecef(station_lat, station_lon, station_alt_m)
    rx, ry, rz = sat_ecef_m[0] - sx, sat_ecef_m[1] - sy, sat_ecef_m[2] - sz
    lat = math.radians(station_lat)
    lon = math.radians(station_lon)
    upx = math.cos(lat) * math.cos(lon)
    upy = math.cos(lat) * math.sin(lon)
    upz = math.sin(lat)
    r_norm = math.sqrt(rx * rx + ry * ry + rz * rz)
    if r_norm < 1e-6:
        return 90.0
    sin_el = (rx * upx + ry * upy + rz * upz) / r_norm
    sin_el = max(-1.0, min(1.0, sin_el))
    return math.degrees(math.asin(sin_el))


class OrbitEngine:
    """Propagates satellites from cached real TLEs via SGP4."""

    def __init__(self, records: list[OrbitalRecord], epoch_utc: datetime):
        self.records = {r.id: r for r in records}
        self.epoch_utc = epoch_utc
        self._sats: dict[str, Satrec] = {}
        for r in records:
            self._sats[r.id] = Satrec.twoline2rv(r.tle_line1, r.tle_line2)

    def datetime_at(self, t_s: float) -> datetime:
        from datetime import timedelta

        return self.epoch_utc + timedelta(seconds=t_s)

    def position_eci_km(self, record_id: str, t_s: float) -> Optional[tuple[float, float, float]]:
        sat = self._sats[record_id]
        dt = self.datetime_at(t_s)
        jd, fr = jday(
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond * 1e-6
        )
        err, r, _v = sat.sgp4(jd, fr)
        if err != 0:
            return None
        return float(r[0]), float(r[1]), float(r[2])

    def position_ecef_m(self, record_id: str, t_s: float) -> Optional[tuple[float, float, float]]:
        eci = self.position_eci_km(record_id, t_s)
        if eci is None:
            return None
        return eci_to_ecef(eci[0], eci[1], eci[2], self.datetime_at(t_s))

    def position_lla(self, record_id: str, t_s: float) -> Optional[dict[str, float]]:
        ecef = self.position_ecef_m(record_id, t_s)
        if ecef is None:
            return None
        lat, lon, alt = ecef_to_lla(*ecef)
        return {"lat": lat, "lon": lon, "alt_km": alt / 1000.0}

    def ground_track(
        self, record_id: str, t0: float, duration_s: float = 5400.0, step_s: float = 60.0
    ) -> list[dict[str, float]]:
        """Sample LLA points for orbit trail visualization."""
        pts: list[dict[str, float]] = []
        t = t0
        end = t0 + duration_s
        while t <= end:
            lla = self.position_lla(record_id, t)
            if lla:
                pts.append(lla)
            t += step_s
        return pts


def load_tle_file(path: Path, source: str = "celestrak-cached") -> list[OrbitalRecord]:
    text = path.read_text()
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    records: list[OrbitalRecord] = []
    i = 0
    while i + 2 < len(lines):
        name = lines[i].strip()
        l1 = lines[i + 1]
        l2 = lines[i + 2]
        if not (l1.startswith("1 ") and l2.startswith("2 ")):
            i += 1
            continue
        sat = Satrec.twoline2rv(l1, l2)
        epoch = sat_epoch_datetime(sat).astimezone(timezone.utc)
        norad = l1[2:7].strip()
        rid = f"tle-{norad}"
        records.append(
            OrbitalRecord(
                id=rid,
                source=source,
                tle_line1=l1,
                tle_line2=l2,
                name=name,
                epoch=epoch.isoformat().replace("+00:00", "Z"),
                norad_id=norad,
            )
        )
        i += 3
    return records


def fetch_or_use_cached(cache_path: Path, fetch_url: Optional[str] = None) -> list[OrbitalRecord]:
    """Prefer in-repo cache; optionally refresh from CelesTrak when online."""
    if fetch_url:
        try:
            import httpx

            resp = httpx.get(fetch_url, timeout=10.0)
            if resp.status_code == 200 and "1 " in resp.text:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(resp.text)
        except Exception:
            pass
    if not cache_path.exists():
        raise FileNotFoundError(f"TLE cache missing: {cache_path}")
    return load_tle_file(cache_path, source=f"file:{cache_path.name}")
