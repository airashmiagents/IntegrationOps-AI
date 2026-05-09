# IntegrationOps-AI

Hackathon project for **AI-assisted SAP Cloud Integration (CPI)** monitoring and autonomous incident analysis: failed Message Processing Logs (MPL), design-time metadata, and an OpenRouter-backed investigation agent with structured JSON output, confidence scoring, and optional SQLite audit trails.

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) — CPI OData clients, APScheduler monitor, SQLite persistence, OpenRouter LLM (with heuristic fallback).
- **Frontend:** [React](https://react.dev/) (Vite) — **Dashboard** (health, run-monitor demo, auto-refreshing incidents every 30s) and **Monitor lifecycle** (incidents + LLM audit + in-process monitor history per MessageGuid).

No Celery, Kafka, Redis, or Kubernetes — stdlib SQLite and APScheduler only.

## Project layout

```text
IntegrationOps-AI/
├── backend/
│   ├── main.py                 # FastAPI app, lifespan (scheduler + DB init); same routes under /api/*
│   ├── requirements.txt        # fastapi, uvicorn, openai, python-dotenv, …
│   ├── Procfile                # Render/Heroku: web → uvicorn main:app --host 0.0.0.0 --port $PORT
│   ├── .env.example            # Copy to .env — CPI, OpenRouter, monitor, SQLite flags
│   ├── agents/                 # run_investigation — CPI → context → LLM
│   ├── models/                 # Pydantic schemas (agent + incidents)
│   ├── routes/                 # health, agent, monitor, observability, incidents
│   └── services/               # cpi_client, ai_service, monitor, incidents_store, llm_audit_sqlite, settings, …
├── frontend/
│   ├── src/pages/
│   │   ├── Dashboard.jsx       # Health, POST /monitor/run-now demo, incidents table (30s poll)
│   │   ├── MockAlertInbox.jsx  # Fake email UI for CPI alert previews (no SMTP)
│   │   └── MonitorLifecycle.jsx  # DB + agent steps + llm_exchange + monitor/history-style buffer
│   ├── src/components/Header.jsx # Nav: Dashboard, Monitor lifecycle
│   └── src/services/api.js     # Health, incidents, monitor, observability helpers
└── README.md
```

Local SQLite files (gitignored): `backend/llm_audit.sqlite` (LLM prompts/responses, keyed by `message_id` when available), `backend/incidents.sqlite` (persisted monitor incidents, deduped by `message_id`).

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Edit: CPI URL, credentials, OpenRouter key, MONITOR_IFLOW_IDS
uvicorn main:app --reload --port 8000   # use any free port, e.g. --port 8005
```

Use **`./.venv/bin/uvicorn`** if you do not activate the venv (ensures `apscheduler` and other deps resolve). The **interactive OpenAPI docs** live at **`http://127.0.0.1:<port>/docs`** on the **same port** you pass to `--port` (not a fixed 8000). Examples: `http://127.0.0.1:8000/docs`, `http://127.0.0.1:8005/docs`. Point the Vite proxy (`VITE_API_PROXY_TARGET`) at that same origin (see Frontend).

#### Deploy backend (Render)

- **ASGI entry:** `main:app` (same as `uvicorn main:app`).
- **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`, or use **`backend/Procfile`** (`web: …`) if the platform picks it up.
- **Root directory:** set to **`backend`** when the repo root is `IntegrationOps-AI`.
- **Build:** `pip install -r requirements.txt`.
- **CORS:** `allow_origins=["*"]` for hackathon demos (any deployed frontend origin). **`allow_credentials=False`** is required with a wildcard origin (browsers reject `*` with credentialed requests).

### Frontend

```bash
cd frontend
cp .env.example .env               # Set VITE_API_PROXY_TARGET if uvicorn is not on port 8000 (e.g. http://127.0.0.1:8005)
npm install
npm run dev
```

In development, the UI defaults to same-origin **`/api/...`**, which Vite proxies to FastAPI (`vite.config.js` → `VITE_API_PROXY_TARGET`). For a **hosted** API (e.g. Render), set **`VITE_API_URL`** to that base URL (no trailing slash); the backend allows **`Origin: *`** style CORS for hackathon use.

Open [http://localhost:5173](http://localhost:5173):

- **/** — Dashboard: **`GET /health`**, **`GET /incidents`**, **`POST /monitor/run-now`** (structured JSON + hints when the cycle skips, e.g. empty `MONITOR_IFLOW_IDS`).
- **/alerts/mock-inbox** — Fake email-client preview of CPI incident alerts (uses **`GET /incidents`** when present, else seeded demos; **`To:`** from **`mock_alert_email`** on **`GET /health`** / **`MOCK_ALERT_EMAIL`** in `backend/.env`).
- **/monitor/lifecycle** — Operator view: each incident joined with **`llm_exchange`** rows and in-memory monitor runs for that MPL MessageGuid; optional **`?message_id=<guid>`** deep link.

## Main API endpoints

Same routes are mounted at the root and under **`/api`** (e.g. `/api/health` and `/health`) for proxies and prefixed clients.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness; includes **`mock_alert_email`** for the mock inbox **`To:`** line |
| `POST` | `/agent/investigate` | On-demand full investigation (CPI + LLM) |
| `GET` | `/monitor/status` | Scheduler config, monitored artifact IDs, runtime fields (e.g. next poll) |
| `GET` | `/monitor/history` | Recent in-memory monitor run summaries (cleared on process restart) |
| `POST` | `/monitor/run-now` | One monitor cycle immediately; response includes `outcomes`, `incidents_stored`, and `skipped`/`hint` when nothing was polled |
| `GET` | `/incidents?limit=100` | Persisted incidents from SQLite (`{ "incidents": [ ... ] }`) |
| `GET` | `/observability/lifecycles` | Incidents + per-row `llm_exchanges`, `monitor_runs`, `agent_canonical_steps` |
| `GET` | `/observability/lifecycle/{message_id}` | Single incident drill-down (404 if not in `incidents` SQLite) |

## Autonomous background monitor

When **`SCHEDULER_ENABLED=true`**, **`CPI_USE_MOCK=false`**, and **`MONITOR_IFLOW_IDS`** lists comma-separated CPI **IntegrationArtifact.Id** values, **APScheduler** runs every **`SCHEDULER_INTERVAL_SEC`** seconds (default **300** = 5 minutes).

Each cycle:

1. Calls SAP CPI OData APIs for recent **FAILED** MPL rows per artifact.
2. If **`MONITOR_IFLOW_IDS`** is empty, the cycle does nothing useful (no CPI poll); **`POST /monitor/run-now`** and the Dashboard surface a **`skipped`** reason and **`hint`** in JSON.
3. Skips duplicates when **`message_id`** (MessageGuid) already exists in **`incidents`** SQLite.
4. Runs the full **`run_investigation`** pipeline (same as `/agent/investigate`).
5. Appends a row to the **`incidents`** table (`error_type`, `severity`, `confidence_score`, `root_cause`, `recommendation`, optional **`jira_ticket_id`**, **`investigation_status`**).

If there are no FAILED rows in the lookback window, the artifact outcome is **`skipped_no_failed_logs`** — no new incident row.

Logs include: monitoring cycle started, incidents found (counts / message id), and incident analysis completed (including whether the row was stored).

## Observability

- **`GET /observability/lifecycles`** — Joins **`incidents.sqlite`** with matching rows from **`llm_audit.sqlite`** (`llm_exchange`), using **`message_id`** when present or a briefing substring match for older audit rows. Also attaches matching entries from the in-process monitor buffer (same source as **`GET /monitor/history`**).
- **Monitor lifecycle** page in the UI consumes this endpoint for demo-friendly drill-down.

## Environment highlights

See **`backend/.env.example`** for the full list. Notable variables:

- **CPI:** `SAP_CPI_BASE_URL`, `SAP_CPI_USER`, `SAP_CPI_PASSWORD`, `CPI_USE_MOCK`, `SAP_CPI_API_ROOT`
- **OpenRouter:** `OPENROUTER_API_KEY` / `LLM_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL`
- **Monitor:** `SCHEDULER_ENABLED`, `SCHEDULER_INTERVAL_SEC`, **`MONITOR_IFLOW_IDS`** (required for real polling), `SCHEDULER_LOOKBACK_MINUTES`
- **SQLite:** `LLM_AUDIT_SQLITE_ENABLED`, `INCIDENTS_SQLITE_ENABLED`, optional `*_SQLITE_PATH` overrides
- **Terminal trace:** `AGENT_TERMINAL_TRACE=true` — step-by-step CPI + LLM narrative to stderr

## Agent output

The LLM returns structured fields including **`confidence_score`** (0–100). The API normalizes enums and clamps scores; a keyword **heuristic** runs when no API key is configured or OpenRouter fails after primary + fallback models.

## Security

Never commit **`backend/.env`** or SQLite files that contain tenant errors or API traffic. Rotate keys if they were exposed.

## License / hackathon

Built for demo and learning; adapt licensing as needed for your org.
