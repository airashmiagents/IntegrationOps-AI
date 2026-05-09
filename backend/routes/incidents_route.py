"""Stored autonomous-monitor incidents — SQLite-backed list for the dashboard."""

from fastapi import APIRouter, Query

from models.schemas import IncidentRecord, IncidentsListResponse
from services.incidents_store import list_incidents

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=IncidentsListResponse)
def get_incidents(limit: int = Query(100, ge=1, le=500)) -> IncidentsListResponse:
    """Latest persisted monitor investigations (newest first)."""
    rows = list_incidents(limit=limit)
    return IncidentsListResponse(incidents=[IncidentRecord.model_validate(r) for r in rows])
