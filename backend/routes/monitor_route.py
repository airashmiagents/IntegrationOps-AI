"""Periodic CPI monitor — status, history, manual run."""

from fastapi import APIRouter

from services.monitor import (
    get_monitor_history,
    get_scheduler_runtime_status,
    monitored_artifact_ids,
    run_monitor_cycle,
)
from services.settings import settings

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/status")
def monitor_status() -> dict:
    """Whether the scheduler is configured and which iFlows are monitored."""
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "cpi_use_mock": settings.cpi_use_mock,
        "interval_sec": settings.scheduler_interval_sec,
        "lookback_minutes": settings.scheduler_lookback_minutes,
        "monitored_artifact_ids": monitored_artifact_ids(),
        **get_scheduler_runtime_status(),
    }


@router.get("/history")
def monitor_history() -> dict:
    """Recent monitor outcomes (newest first)."""
    return {"runs": get_monitor_history()}


@router.post("/run-now")
def monitor_run_now() -> dict:
    """Trigger one monitor cycle immediately (for demos / tests)."""
    summary = run_monitor_cycle(force=True)
    return {
        "ok": True,
        "message": "Cycle finished — see outcomes for per-artifact results and GET /monitor/history.",
        **summary,
    }
