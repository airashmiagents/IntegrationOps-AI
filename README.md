# IntegrationOps-AI

Hackathon project for **AI-assisted SAP Cloud Integration (CPI)** monitoring and autonomous incident analysis: failed Message Processing Logs (MPL), design-time metadata, and an OpenRouter-backed investigation agent with structured JSON output, confidence scoring, and optional SQLite audit trails.

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) — CPI OData clients, APScheduler monitor, SQLite persistence, OpenRouter LLM (with heuristic fallback).
- **Frontend:** [React](https://react.dev/) (Vite) — dashboard with health check and **auto-refreshing incidents** (30s) from `GET /incidents`.

No Celery, Kafka, Redis, or Kubernetes — stdlib SQLite and APScheduler only.

## Project layout

```text
IntegrationOps-AI/
├── backend/
│   ├── main.py                 # FastAPI app, lifespan (scheduler + DB init)
│   ├── requirements.txt
│   ├── .env.example            # Copy to .env — CPI, OpenRouter, monitor, SQLite flags
│   ├── agents/                 # run_investigation — CPI → context → LLM
│   ├── models/                 # Pydantic schemas (agent + incidents)
│   ├── routes/                 # health, agent, monitor, incidents
│   └── services/               # cpi_client, ai_service, monitor, incidents_store, llm_audit_sqlite, settings
├── frontend/
│   ├── src/pages/Dashboard.jsx # Health + incidents table (30s poll)
│   └── src/services/api.js     # fetchHealth, fetchIncidents
└── README.md
```

Local SQLite files (gitignored): `backend/llm_audit.sqlite` (LLM prompts/responses), `backend/incidents.sqlite` (persisted monitor incidents).

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Edit: CPI URL, credentials, OpenRouter key, monitor IDs
uvicorn main:app --reload --port 8000
```

Use **`./.venv/bin/uvicorn`** if you do not activate the venv (ensures `apscheduler` and other deps resolve).

Open [http://localhost:8000/docs](http://localhost:8000/docs) for interactive API docs.

### Frontend

```bash
cd frontend
cp .env.example .env               # Set VITE_API_URL to match backend (e.g. http://127.0.0.1:8000)
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The dashboard loads **`GET /health`** and **`GET /incidents`** every **30 seconds**.

## Main API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness |
| `POST` | `/agent/investigate` | On-demand full investigation (CPI + LLM) |
| `GET` | `/monitor/status` | Scheduler config and monitored artifact IDs |
| `GET` | `/monitor/history` | Recent in-memory monitor run summaries |
| `POST` | `/monitor/run-now` | Force one monitor cycle (for demos) |
| `GET` | `/incidents?limit=100` | Persisted incidents from SQLite (`{ "incidents": [ ... ] }`) |

## Autonomous background monitor

When **`SCHEDULER_ENABLED=true`**, **`CPI_USE_MOCK=false`**, and **`MONITOR_IFLOW_IDS`** lists comma-separated CPI **IntegrationArtifact.Id** values, **APScheduler** runs every **`SCHEDULER_INTERVAL_SEC`** seconds (default **300** = 5 minutes).

Each cycle:

1. Calls SAP CPI OData APIs for recent **FAILED** MPL rows per artifact.
2. Skips duplicates when **`message_id`** (MessageGuid) already exists in **`incidents`** SQLite.
3. Runs the full **`run_investigation`** pipeline (same as `/agent/investigate`).
4. Appends a row to the **`incidents`** table (`error_type`, `severity`, `confidence_score`, `root_cause`, `recommendation`, optional **`jira_ticket_id`**, **`investigation_status`**).

Logs include: monitoring cycle started, incidents found (counts / message id), and incident analysis completed (including whether the row was stored).

## Environment highlights

See **`backend/.env.example`** for the full list. Notable variables:

- **CPI:** `SAP_CPI_BASE_URL`, `SAP_CPI_USER`, `SAP_CPI_PASSWORD`, `CPI_USE_MOCK`, `SAP_CPI_API_ROOT`
- **OpenRouter:** `OPENROUTER_API_KEY` / `LLM_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL`
- **Monitor:** `SCHEDULER_ENABLED`, `SCHEDULER_INTERVAL_SEC`, `MONITOR_IFLOW_IDS`, `SCHEDULER_LOOKBACK_MINUTES`
- **SQLite:** `LLM_AUDIT_SQLITE_ENABLED`, `INCIDENTS_SQLITE_ENABLED`, optional `*_SQLITE_PATH` overrides
- **Terminal trace:** `AGENT_TERMINAL_TRACE=true` — step-by-step CPI + LLM narrative to stderr

## Agent output

The LLM returns structured fields including **`confidence_score`** (0–100). The API normalizes enums and clamps scores; a keyword **heuristic** runs when no API key is configured or OpenRouter fails after primary + fallback models.

## Security

Never commit **`backend/.env`** or SQLite files that contain tenant errors or API traffic. Rotate keys if they were exposed.

## License / hackathon

Built for demo and learning; adapt licensing as needed for your org.
