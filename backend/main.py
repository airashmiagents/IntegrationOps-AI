"""
IntegrationOps-AI — FastAPI entrypoint.

backend/
--------
Python API for CPI monitoring hooks and AI-assisted incident analysis.

Run locally:  uvicorn main:app --reload --port 8000
API docs:      http://localhost:8000/docs
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

# Allow the Vite dev server to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "IntegrationOps-AI API — see /docs for endpoints"}
