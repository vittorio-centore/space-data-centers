#!/usr/bin/env python3
"""Replay the four-tenant market day and print the metric row.

  cd backend && PYTHONPATH=. python3 scripts/market_day.py --seed 7 --n 4
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
from app.eval.market_day import MARKET_TENANTS, run_market_day
from app.sim.world import SimWorld


async def main() -> None:
    p = argparse.ArgumentParser(description="Space Data Centers market-day replay")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--n", type=int, default=4, help="jobs per tenant")
    p.add_argument("--max-steps", type=int, default=2500)
    p.add_argument("--db", type=Path, default=None)
    p.add_argument(
        "--tenants",
        default=",".join(MARKET_TENANTS),
        help="comma-separated tenant ids (default alpha,beta,gamma,delta)",
    )
    args = p.parse_args()
    tenants = tuple(t.strip() for t in args.tenants.split(",") if t.strip())
    db = args.db or (ROOT / "data" / "market-day.sqlite")
    cfg = AppConfig(db_path=db, persist=True, headless=True, scenario="mvp-thesis", log_json=False)
    world = SimWorld(cfg, restore=False)
    try:
        report = await run_market_day(
            world,
            seed=args.seed,
            n_per_tenant=args.n,
            max_steps=args.max_steps,
            tenants=tenants,
        )
        row = {
            "tenants": report.tenants,
            "deadline_hit_rate": {k: report.deadline_hit_rate.get(k) for k in report.tenants},
            "deadline_hit_rate[reservation_aware]": report.deadline_hit_rate.get("reservation_aware"),
            "stolen_windows": report.stolen_windows,
            "hit_rate_equity": report.hit_rate_equity,
            "hit_rate_equity_ignores_tenants": report.hit_rate_equity_ignores_tenants,
            "min_tenant_hit_rate": report.min_tenant_hit_rate,
            "min_tenant_hit_rate_ignores_tenants": report.min_tenant_hit_rate_ignores_tenants,
            "cost_reservation_aware": report.cost_reservation_aware,
            "cost_global_cheapest_ignores_tenants": report.cost_global_cheapest_ignores_tenants,
            "deadline_hit_rate_ignores_tenants": report.deadline_hit_rate_ignores_tenants,
            "fairness_beats_ignore_tenants": report.fairness_beats_ignore_tenants,
            "delta_cost": report.delta_cost,
            "id": report.id,
            "seed": report.seed,
            "n_jobs": report.n_jobs,
        }
        print(json.dumps(row, indent=2))
        if report.stolen_windows != 0:
            raise SystemExit("stolen_windows must be 0")
    finally:
        world.close()


if __name__ == "__main__":
    asyncio.run(main())
