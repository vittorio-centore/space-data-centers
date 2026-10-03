#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 43124 &
BACK_PID=$!
cd "$ROOT/frontend"
npm run dev -- --host 0.0.0.0 --port 43123 &
FRONT_PID=$!
trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
wait
