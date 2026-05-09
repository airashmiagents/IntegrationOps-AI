# IntegrationOps-AI

Hackathon starter for an **AI-assisted SAP Cloud Integration (CPI)** monitoring and incident analysis tool.

- **Backend:** Python [FastAPI](https://fastapi.tiangolo.com/) — REST API, CPI clients, and AI helpers.
- **Frontend:** [React](https://react.dev/) (Vite) — dashboards and incident views.

## Project layout

```text
IntegrationOps-AI/
├── backend/           # FastAPI app — run API from this folder
│   ├── main.py        # App entry, CORS, router wiring
│   ├── requirements.txt
│   ├── .env           # Local secrets (gitignored after first clone — use .env.example)
│   ├── models/        # Pydantic schemas for requests/responses
│   ├── routes/        # HTTP endpoints (thin controllers)
│   ├── services/      # CPI/API clients, config, integrations
│   └── agents/        # LLM prompts and incident summarization logic
├── frontend/          # React (Vite) — UI dev server from this folder
│   └── src/
│       ├── components/   # Reusable UI (headers, cards, tables)
│       ├── pages/        # Route-level screens
│       └── services/     # fetch/axios wrappers for the API
└── README.md
```

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # if you don’t already have .env
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs).

### Frontend

```bash
cd frontend
cp .env.example .env   # optional — sets VITE_API_URL for the API
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The dashboard calls `GET /health` on the API.

## Hackathon tips

1. Add CPI OAuth and message-log calls under `backend/services/`.
2. Keep one LLM entrypoint in `backend/agents/` (e.g. summarize error payloads).
3. Add new FastAPI routes in `backend/routes/` and mirror them in `frontend/src/services/`.

Keep schemas small, demo often, and ship a vertical slice (one integration flow end-to-end) before polishing extras.
