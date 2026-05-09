"""
routes/
-------
FastAPI routers: HTTP endpoints only.

Split by feature (`health.py`, `incidents.py`, …) so teammates can work in parallel.
"""

from fastapi import APIRouter

from .agent_route import router as agent_router
from .health import router as health_router
from .incidents_route import router as incidents_router
from .monitor_route import router as monitor_router
from .observability_route import router as observability_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(agent_router)
api_router.include_router(monitor_router)
api_router.include_router(observability_router)
api_router.include_router(incidents_router)
