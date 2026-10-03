"""Real image-batch worker: resize a set of generated images (wall-clock work)."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def run_batch(work_units: float, out_dir: Path) -> dict:
    """Map work_units to image count; perform real CPU-bound transforms."""
    n = max(4, min(60, int(work_units / 5)))
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for i in range(n):
        img = Image.new("RGB", (640, 480), color=(20 + i * 3, 40, 80))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 600, 440], outline=(220, 180, 40), width=3)
        draw.text((60, 60), f"SDC batch {i}", fill=(240, 240, 240))
        img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
        img = img.resize((320, 240))
        img.save(out_dir / f"frame_{i:03d}.jpg", quality=85)
    elapsed = time.perf_counter() - t0
    return {"images": n, "wall_seconds": elapsed, "out_dir": str(out_dir)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    p.add_argument("--work", type=float, required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        result = run_batch(args.work, Path(args.out))
        result["job_id"] = args.job_id
        result["ok"] = True
        print(json.dumps(result))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "job_id": args.job_id}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
