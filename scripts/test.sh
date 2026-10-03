#!/usr/bin/env bash
# One command for the full Space Data Centers suite (backend + frontend + optional Playwright).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== backend pytest =="
cd "$ROOT/backend"
export SDC_PERSIST="${SDC_PERSIST:-0}"
export SDC_HEADLESS="${SDC_HEADLESS:-1}"
export SDC_SCENARIO="${SDC_SCENARIO:-mvp-thesis}"
PYTHONPATH=. python3 -m pytest "${@:-}"

echo "== frontend vitest =="
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm test

if [[ "${SDC_SKIP_PLAYWRIGHT:-0}" != "1" ]]; then
  echo "== frontend playwright =="
  if ! npx playwright test; then
    echo "Playwright failed; retry after: cd frontend && npx playwright install chromium"
    exit 1
  fi
fi

echo "All suites passed."
