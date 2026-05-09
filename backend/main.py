"""
IntegrationOps-AI — FastAPI entrypoint.

backend/
--------
Python API for CPI monitoring hooks and AI-assisted incident analysis.

Run locally:  uvicorn main:app --reload --port 8000
Deploy:       uvicorn main:app --host 0.0.0.0 --port $PORT  (see Procfile in this folder)
API docs:      http://localhost:<port>/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import api_router
from services.agent_trace import configure_terminal_trace_logging
from services.incidents_store import init_incidents_db
from services.llm_audit_sqlite import init_llm_audit_db
from services.monitor import start_monitor_scheduler, stop_monitor_scheduler
from services.settings import settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start optional APScheduler CPI monitor on process startup."""
    configure_terminal_trace_logging()
    init_llm_audit_db()
    init_incidents_db()
    start_monitor_scheduler()
    yield
    stop_monitor_scheduler()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

# Hackathon / Render: allow any frontend origin. ``allow_origins=["*"]`` requires
# ``allow_credentials=False`` (browser + ASGI spec — wildcard cannot be combined with credentialed CORS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
# Also serve the same API under ``/api/*`` so clients or proxies that prefix paths (e.g. ``/api/incidents``) work.
app.include_router(api_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "IntegrationOps-AI API — see /docs for endpoints"}
