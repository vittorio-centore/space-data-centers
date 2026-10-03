#!/usr/bin/env python3
"""Fetch-or-use-cached TLEs for MVP orbital nodes.

Default: refresh the three NORAD IDs used by the sim from CelesTrak groups,
falling back to the in-repo cache on network failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "tles" / "leo_compute.tle"

# NORAD IDs documented in README
WANTED = {
    "25544": "ISS (ZARYA)",
    "48274": "CSS (TIANHE)",
    "43013": "NOAA 20 (JPSS-1)",
}

URLS = [
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
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


def main() -> int:
    found: dict[str, tuple[str, str, str]] = {}
    try:
        for url in URLS:
            resp = httpx.get(url, timeout=15.0)
            resp.raise_for_status()
            found.update(parse(resp.text))
    except Exception as e:
        print(f"fetch failed ({e}); keeping cache at {CACHE}", file=sys.stderr)
        return 0 if CACHE.exists() else 1

    lines: list[str] = []
    for norad, label in WANTED.items():
        if norad not in found:
            print(f"missing {norad} ({label})", file=sys.stderr)
            return 1
        name, l1, l2 = found[norad]
        lines.extend([name, l1, l2])
        print(f"OK {norad} {name}")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text("\n".join(lines) + "\n")
    print(f"wrote {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
