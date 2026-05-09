"""
routes/
-------
FastAPI routers: HTTP endpoints only.

Split by feature (`health.py`, `incidents.py`, …) so teammates can work in parallel.
"""

from fastapi import APIRouter

from .agent_route import router as agent_router
from .health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(agent_router)
