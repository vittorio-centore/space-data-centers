from app.orbit.contacts import earth_occludes
from app.orbit.propagate import elevation_deg, geodetic_to_ecef, range_m


def test_geodetic_roundtrip_ecef_near_surface():
    x, y, z = geodetic_to_ecef(39.04, -77.49, 80.0)
    assert abs((x * x + y * y + z * z) ** 0.5 - 6.37e6) < 5e4


def test_elevation_overhead():
    lat, lon, alt = 0.0, 0.0, 0.0
    sx, sy, sz = geodetic_to_ecef(lat, lon, alt)
    sat = (sx * 1.2, sy * 1.2, sz * 1.2)
    el = elevation_deg(lat, lon, alt, sat)
    assert el > 80


def test_sgp4_iss_position(world):
    rec = next(r for r in world.records if r.norad_id == "25544")
    ecef = world.orbit.position_ecef_m(rec.id, 0.0)
    assert ecef is not None
    r = range_m((0, 0, 0), ecef)
    assert 6.6e6 < r < 7.0e6


def test_position_cache_stable(world):
    rec = world.records[0]
    a = world.orbit.position_ecef_m(rec.id, 10.0)
    b = world.orbit.position_ecef_m(rec.id, 10.0)
    assert a == b


def test_earth_occludes_diameter():
    a = (8e6, 0.0, 0.0)
    b = (-8e6, 0.0, 0.0)
    assert earth_occludes(a, b)
    c = (8e6, 8e6, 0.0)
    assert not earth_occludes(a, c)
