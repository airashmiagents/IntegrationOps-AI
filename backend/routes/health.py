"""Health check — proves backend + React can talk during demos."""

from fastapi import APIRouter

from models.schemas import HealthResponse
from services.settings import settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app_name=settings.app_name)
