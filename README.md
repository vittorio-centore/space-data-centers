# Space Data Centers

Job-placement planner for Earth and orbital data centers. Submit a batch job; the planner picks a compute node and store-and-forward routes using **real SGP4 contact windows** from public TLEs, then the sim animates transfers while a **real image-resize worker** runs. The dashboard compares the chosen plan to a cheapest-node baseline — including thesis Case A/B where cheap orbital loses when the next contact is too late, and wins under different phasing.

The planner is **deterministic**: same scenario, inputs, and seed produce the same plan.

This branch adds a **shared-sky control plane**: tenants (`local`, `alpha`, `beta`) share one contact graph and one reservation table. Reservations are hard-exclusive (no double-book). Optional per-tenant API keys; when keys are unset every request is the documented default tenant `local`, which still cannot overwrite another tenant’s rows. Single WAL owner (`flock`) — not a cluster.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React + TypeScript (Vite), Three.js globe |
| Backend | Python + FastAPI, `/api/v1` + legacy root aliases, WebSocket `/ws` |
| Orbit | SGP4 from cached CelesTrak TLEs (`backend/data/tles/`) |
| Workers | Local asyncio subprocess — image batch resize (skipped when `SDC_HEADLESS=1`) |
| Assistant | Grok Ask + xAI Voice (optional `XAI_API_KEY`); offline parser if unset |
| State | SQLite WAL (`backend/data/sdc.sqlite`) with in-memory fallback when `SDC_PERSIST=0` |

## Satellite choices (real TLEs)

| Node | NORAD | Name | Role |
| --- | --- | --- | --- |
| `orbital-iss-cheap` | **25544** | ISS (ZARYA) | Cheapest orbital compute (thesis) |
| `orbital-css` | **48274** | CSS (TIANHE) | Mid-price orbital |
| `orbital-noaa` | **43013** | NOAA 20 (JPSS-1) | Polar LEO orbital |

Ground stations (mvp-thesis): **Ashburn, VA** and **Madrid**. Scenario `leo-constellation` adds Svalbard, Singapore, Santiago, Perth, a second Earth DC, and more TLE-bound nodes.

Refresh TLEs (optional; cache works offline):

```bash
cd backend && python3 scripts/fetch_tles.py
```

## Run locally

Ports: frontend **43123**, backend **43124**.

```bash
cd backend
python3 -m pip install -r requirements.txt
PYTHONPATH=. python3 -m uvicorn app.main:app --host 0.0.0.0 --port 43124

cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 43123
```

- API docs: [http://127.0.0.1:43124/docs](http://127.0.0.1:43124/docs)
- Inspector contact matrix: `GET /api/v1/contacts` (same sim-step grid the planner uses)
- Isolated operator page: [http://127.0.0.1:43124/operator/](http://127.0.0.1:43124/operator/) (includes **Market day**)
- Dashboard: [http://127.0.0.1:43123](http://127.0.0.1:43123)

### Market-day replay

Two tenants, one overload script, reservation-aware planner vs `cheapest` with tenant ids stripped:

```bash
cd backend && PYTHONPATH=. python3 scripts/market_day.py --seed 11 --n 5
# or
curl -X POST http://127.0.0.1:43124/api/v1/evaluations/market-day \
  -H 'Content-Type: application/json' \
  -d '{"seed":11,"n_per_tenant":5,"max_steps":2500}'
```

The printed row includes `deadline_hit_rate[alpha]`, `deadline_hit_rate[beta]`, `stolen_windows` (must be 0), `cost_reservation_aware`, `cost_global_cheapest_ignores_tenants`, and the ignore-tenants hit rate. Report is persisted in SQLite when `SDC_PERSIST=1`.

### Grok Ask + xAI Voice

The collapsible **Ask Grok** panel shares one assistant for typed commands and voice. Allowed tools: read state, explain plans, submit jobs, play/pause, disrupt links. **Every action is validated** on the backend. Submit never accepts a node id — the deterministic planner still places the job.

```bash
export XAI_API_KEY=xai-...          # required for live Grok + xAI STT/TTS
export XAI_MODEL=grok-4             # optional (default grok-4)
export XAI_API_BASE=https://api.x.ai/v1
export XAI_STT_MODEL=grok-voice-transcribe-2.0
export XAI_TTS_VOICE=eve
# then start the backend as above
```

Without a key the same tools run through a keyword intent parser. The Ask panel and every reply are labelled **Offline (no XAI_API_KEY)**. Voice then uses the browser speech API and still hits `POST /assistant/ask`. Live voice posts audio to `POST /assistant/voice` (`POST /v1/stt`), then the same validated pipeline; replies may include TTS (`POST /v1/tts`). Live Grok uses the Responses API (`POST /v1/responses`) with a chat/completions fallback, then sends validated tool results back for a short summary.

```bash
cd backend && PYTHONPATH=. python3 -m pytest tests/test_assistant_intents.py tests/test_assistant_parser.py tests/test_assistant_parser_edges.py tests/test_assistant_grok.py tests/test_assistant_service.py
```

### Thesis demos

```bash
curl -X POST http://127.0.0.1:43124/api/v1/presets/thesis/a
curl -X POST http://127.0.0.1:43124/api/v1/presets/thesis/b
```

Legacy unversioned paths (`/health`, `/jobs`, …) remain for the current frontend proxy.

### Tests

One command (backend pytest + frontend Vitest + Playwright smoke):

```bash
./scripts/test.sh
```

Markers: `unit`, `integration`, `e2e`. Skip browser smoke with `SDC_SKIP_PLAYWRIGHT=1`. Subsets:

```bash
cd backend && PYTHONPATH=. python3 -m pytest -q -m unit
cd backend && PYTHONPATH=. python3 -m pytest -q -m integration
cd backend && PYTHONPATH=. python3 -m pytest -q -m e2e
cd frontend && npm test
cd frontend && npm run test:e2e   # after: npx playwright install chromium
```

Tests drive the **sim clock** (`seek` / `step`); they do not `sleep` on wall time. See the project testing notes for the coverage map.

### Env

| Variable | Default | Meaning |
| --- | --- | --- |
| `SDC_DB_PATH` | `backend/data/sdc.sqlite` | SQLite file |
| `SDC_PERSIST` | `1` | Write-through persistence |
| `SDC_HEADLESS` | `0` | Skip real workers (eval/tests) |
| `SDC_SCENARIO` | `mvp-thesis` | `mvp-thesis` or `leo-constellation` |
| `API_KEY` | unset (open) | If set, require `X-API-Key` or `Authorization: Bearer`. Maps to tenant `local` (or `SDC_DEFAULT_TENANT`). Demo value: `sdc-demo`. `/health` and `/ready` stay open. |
| `SDC_TENANT_KEYS` | unset | Optional `key:tenant` map, e.g. `sdc-alpha:alpha,sdc-beta:beta`. Enables per-tenant keys. Open mode always acts as `local`. |
| `SDC_DEFAULT_TENANT` | `local` | Default-open tenant id. Cannot smash seeded `alpha`/`beta` rows. |
| `SDC_INSTANCE_LOCK` | `1` | Exclusive flock on `<db>.owner.lock`. One WAL owner; not a cluster. Set `0` only for unsupported experiments. |
| `XAI_API_KEY` | unset | Enables live Grok + xAI Voice. Unset = offline parser (no outbound xAI calls). |
| `XAI_API_BASE` | `https://api.x.ai/v1` | xAI HTTP base. |
| `XAI_MODEL` | `grok-4` | Responses / chat model. |
| `XAI_STT_MODEL` | `grok-voice-transcribe-2.0` | Speech-to-text model. |
| `XAI_TTS_VOICE` | `eve` | TTS `voice_id`. |

## Reality boundary

| Real / derived | Simulated / labelled |
| --- | --- |
| TLE ephemeris, SGP4 positions | Compute FLOPS / queues / prices |
| Contact windows (elevation/range/ISL occlusion) | Link bandwidth & bit pricing |
| Configured GS lat/lon | Power/thermal (assumption-labelled, not telemetry) |

## Units

Seconds, meters, bytes, bit/s (bandwidth), dollars.
