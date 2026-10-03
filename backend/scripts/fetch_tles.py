#!/usr/bin/env python3
"""Fetch-or-use-cached TLEs for MVP and constellation scenarios."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "tles" / "leo_compute.tle"
CONST = ROOT / "data" / "tles" / "leo_constellation.tle"

WANTED = {
    "25544": "ISS (ZARYA)",
    "48274": "CSS (TIANHE)",
    "43013": "NOAA 20 (JPSS-1)",
}

EXTRA = {
    "20580": "HST",
    "25994": "TERRA",
    "27424": "AQUA",
    "39084": "LANDSAT 8",
    "40697": "SENTINEL-2A",
    "41335": "SENTINEL-3A",
    "37849": "SUOMI NPP",
    "43013": "NOAA 20",
    "33591": "NOAA 19",
    "28654": "NOAA 18",
    "38771": "METOP-B",
}

URLS = [
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=resource&FORMAT=tle",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=science&FORMAT=tle",
]


def parse(text: str) -> dict[str, tuple[str, str, str]]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out: dict[str, tuple[str, str, str]] = {}
    i = 0
    while i + 2 < len(lines):
        name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            norad = l1[2:7].strip()
            out[norad] = (name, l1, l2)
            i += 3
        else:
            i += 1
    return out


def write_set(path: Path, wanted: dict[str, str], found: dict[str, tuple[str, str, str]]) -> int:
    lines: list[str] = []
    missing = 0
    for norad, label in wanted.items():
        if norad not in found:
            print(f"missing {norad} ({label})", file=sys.stderr)
            missing += 1
            continue
        name, l1, l2 = found[norad]
        lines.extend([name, l1, l2])
        print(f"OK {norad} {name}")
    if not lines:
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    print(f"wrote {path}")
    return 0 if missing == 0 else 0


def main() -> int:
    found: dict[str, tuple[str, str, str]] = {}
    try:
        for url in URLS:
            resp = httpx.get(url, timeout=15.0)
            resp.raise_for_status()
            found.update(parse(resp.text))
    except Exception as e:
        print(f"fetch failed ({e}); keeping caches", file=sys.stderr)
        return 0 if CACHE.exists() else 1

    write_set(CACHE, WANTED, found)
    write_set(CONST, EXTRA, found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
