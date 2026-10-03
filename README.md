# Space Data Centers

Job-placement planner for Earth and orbital data centers. Submit a batch job; the planner picks a compute node and store-and-forward routes using **real SGP4 contact windows** from public TLEs, then the sim animates transfers while a **real image-resize worker** runs. The dashboard compares the chosen plan to a cheapest-node baseline — including thesis Case A/B where cheap orbital loses when the next contact is too late, and wins under different phasing.

The planner is **deterministic**: same scenario, inputs, and seed produce the same plan.

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
- Isolated operator page: [http://127.0.0.1:43124/operator/](http://127.0.0.1:43124/operator/)
- Dashboard: [http://127.0.0.1:43123](http://127.0.0.1:43123)

### Grok Ask + xAI Voice

The collapsible **Ask Grok** panel shares one assistant for typed commands and voice. Allowed tools: read state, explain plans, submit jobs, play/pause, disrupt links. **Every action is validated** on the backend. Submit never accepts a node id — the deterministic planner still places the job.

```bash
export XAI_API_KEY=xai-...          # required for live Grok + xAI STT/TTS
export XAI_MODEL=grok-4             # optional
export XAI_API_BASE=https://api.x.ai/v1
# then start the backend as above
```

Without a key the same tools run through a keyword intent parser. Voice then uses the browser speech API and still hits `POST /assistant/ask`. Live voice posts audio to `POST /assistant/voice` (xAI STT), then the same validated pipeline; replies may include TTS.

```bash
cd backend && PYTHONPATH=. python3 -m pytest tests/test_assistant_intents.py tests/test_assistant_parser.py
```

### Thesis demos

```bash
curl -X POST http://127.0.0.1:43124/api/v1/presets/thesis/a
curl -X POST http://127.0.0.1:43124/api/v1/presets/thesis/b
```

Legacy unversioned paths (`/health`, `/jobs`, …) remain for the current frontend proxy.

### Tests

```bash
cd backend && PYTHONPATH=. python3 -m pytest -q
```

### Env

| Variable | Default | Meaning |
| --- | --- | --- |
| `SDC_DB_PATH` | `backend/data/sdc.sqlite` | SQLite file |
| `SDC_PERSIST` | `1` | Write-through persistence |
| `SDC_HEADLESS` | `0` | Skip real workers (eval/tests) |
| `SDC_SCENARIO` | `mvp-thesis` | `mvp-thesis` or `leo-constellation` |

## Reality boundary

| Real / derived | Simulated / labelled |
| --- | --- |
| TLE ephemeris, SGP4 positions | Compute FLOPS / queues / prices |
| Contact windows (elevation/range/ISL occlusion) | Link bandwidth & bit pricing |
| Configured GS lat/lon | Power/thermal (assumption-labelled, not telemetry) |

## Units

Seconds, meters, bytes, bit/s (bandwidth), dollars.
