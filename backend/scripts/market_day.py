#!/usr/bin/env python3
"""Replay the two-tenant market day and print the metric row.

  cd backend && PYTHONPATH=. python3 scripts/market_day.py --seed 11 --n 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import AppConfig
from app.eval.market_day import run_market_day
from app.sim.world import SimWorld


async def main() -> None:
    p = argparse.ArgumentParser(description="Space Data Centers market-day replay")
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--n", type=int, default=5, help="jobs per tenant")
    p.add_argument("--max-steps", type=int, default=2500)
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args()
    db = args.db or (ROOT / "data" / "market-day.sqlite")
    cfg = AppConfig(db_path=db, persist=True, headless=True, scenario="mvp-thesis", log_json=False)
    world = SimWorld(cfg, restore=False)
    try:
        report = await run_market_day(
            world, seed=args.seed, n_per_tenant=args.n, max_steps=args.max_steps
        )
        row = {
            "deadline_hit_rate[alpha]": report.deadline_hit_rate.get("alpha"),
            "deadline_hit_rate[beta]": report.deadline_hit_rate.get("beta"),
            "stolen_windows": report.stolen_windows,
            "cost_reservation_aware": report.cost_reservation_aware,
            "cost_global_cheapest_ignores_tenants": report.cost_global_cheapest_ignores_tenants,
            "deadline_hit_rate_ignores_tenants": report.deadline_hit_rate_ignores_tenants,
            "delta_cost": report.delta_cost,
            "id": report.id,
            "seed": report.seed,
        }
        print(json.dumps(row, indent=2))
        if report.stolen_windows != 0:
            raise SystemExit("stolen_windows must be 0")
    finally:
        world.close()


if __name__ == "__main__":
    asyncio.run(main())
