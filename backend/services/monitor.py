"""
Periodic CPI monitor — APScheduler every N seconds (default 5 min).

FAILED MPL → dedupe by ``message_id`` in SQLite → full ``run_investigation`` agent → persist ``incidents`` table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from agents.agent import run_investigation
from services.agent_trace import summarize_runtime_logs, trace
from services.cpi_client import fetch_recent_failed_logs
from services.incidents_store import has_message_id, insert_incident
from services.settings import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_history: list[dict[str, Any]] = []
_MAX_HISTORY = 30


def monitored_artifact_ids() -> list[str]:
    raw = (settings.monitor_iflow_ids or "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()]


def get_scheduler_runtime_status() -> dict[str, Any]:
    """
    Whether APScheduler actually started in this process and when the next CPI poll is due.

    ``start_monitor_scheduler`` is skipped when ``SCHEDULER_ENABLED`` is false or ``CPI_USE_MOCK`` is true,
    so ``scheduler_process_running`` can be false even if ``scheduler_enabled`` is true in ``.env``.
    """
    global _scheduler
    if _scheduler is None or not _scheduler.running:
        return {
            "scheduler_process_running": False,
            "next_cpi_poll_at": None,
            "poll_interval_sec_active": None,
        }
    job = _scheduler.get_job("cpi_failed_log_monitor")
    nrt = job.next_run_time if job else None
    nrt_out: str | None = None
    if nrt is not None:
        nrt_out = nrt.isoformat() if nrt.tzinfo else nrt.replace(tzinfo=timezone.utc).isoformat()
    return {
        "scheduler_process_running": True,
        "next_cpi_poll_at": nrt_out,
        "poll_interval_sec_active": max(60, int(settings.scheduler_interval_sec)),
    }


def get_monitor_history() -> list[dict[str, Any]]:
    """Last N scheduler / manual runs (newest first)."""
    return list(reversed(_history[-_MAX_HISTORY :]))


def run_monitor_cycle(*, force: bool = False) -> dict[str, Any]:
    """
    One poll: for each configured artifact Id, pull recent FAILED MPL rows, skip duplicates
    (``message_id`` already in ``incidents`` SQLite), then run the full investigation agent.

    Returns a JSON-serializable summary for ``POST /monitor/run-now`` and demos.
    """
    if not force and not settings.scheduler_enabled:
        return {"skipped": "scheduler_disabled", "polled_artifact_ids": [], "outcomes": [], "incidents_stored": 0}

    if settings.cpi_use_mock:
        logger.debug("Monitor cycle skipped: CPI_USE_MOCK=true")
        return {
            "skipped": "cpi_use_mock",
            "hint": "Set CPI_USE_MOCK=false in backend/.env with real SAP_CPI_BASE_URL / user / password, then restart uvicorn (from the backend folder so .env loads).",
            "polled_artifact_ids": [],
            "outcomes": [],
            "incidents_stored": 0,
        }

    ids = monitored_artifact_ids()
    if not ids:
        logger.warning("Monitor enabled but MONITOR_IFLOW_IDS is empty — nothing to poll")
        return {
            "skipped": "empty_monitor_iflow_ids",
            "hint": "Set MONITOR_IFLOW_IDS in backend/.env to comma-separated CPI IntegrationArtifact.Id values (design-time artifact Id), save the file, then restart uvicorn from the backend directory so settings reload.",
            "polled_artifact_ids": [],
            "outcomes": [],
            "incidents_stored": 0,
        }

    logger.info("Monitoring cycle started — %d artifact(s): %s", len(ids), ids)
    trace(
        "Monitor cycle ▶  force=%s  artifact_ids=%s  lookback_min=%s  cpi_mock=%s"
        % (force, ids, settings.scheduler_lookback_minutes, settings.cpi_use_mock)
    )

    outcomes: list[dict[str, Any]] = []
    stored_total = 0
    for aid in ids:
        try:
            outcome = _process_one_artifact(aid)
            outcomes.append({"artifact_id": aid, "result": outcome})
            if outcome == "stored":
                stored_total += 1
        except Exception as exc:  # noqa: BLE001 — keep scheduler alive
            logger.exception("Monitor cycle failed for artifact_id=%s: %s", aid, exc)
            _record(
                artifact_id=aid,
                message_guid=None,
                skipped=False,
                skip_reason=None,
                analysis=None,
                error=f"exception: {exc}",
            )
            outcomes.append({"artifact_id": aid, "result": "exception", "detail": str(exc)[:800]})

    return {
        "polled_artifact_ids": ids,
        "outcomes": outcomes,
        "incidents_stored": stored_total,
    }


def _process_one_artifact(artifact_id: str) -> str:
    """
    Poll one artifact; persist a new incident when appropriate.

    Return value is surfaced in ``POST /monitor/run-now`` ``outcomes[].result``.
    """
    logs = fetch_recent_failed_logs(
        artifact_id,
        lookback_minutes=settings.scheduler_lookback_minutes,
        top=25,
    )
    if not logs:
        trace("Monitor: artifact=%s → skip (no FAILED MPL rows in lookback window)" % artifact_id)
        _record(
            artifact_id=artifact_id,
            message_guid=None,
            skipped=True,
            skip_reason="no_failed_logs_in_window",
            analysis=None,
            error=None,
        )
        return "skipped_no_failed_logs"

    trace(
        "Monitor: artifact=%s  fetch_recent_failed_logs → %s"
        % (artifact_id, summarize_runtime_logs(logs))
    )

    newest = logs[0]
    mid = (newest.get("message_id") or "").strip()
    if not mid:
        trace("Monitor: artifact=%s → skip (newest FAILED row has no MessageGuid)" % artifact_id)
        _record(
            artifact_id=artifact_id,
            message_guid=None,
            skipped=True,
            skip_reason="missing_message_guid",
            analysis=None,
            error=None,
        )
        return "skipped_missing_message_guid"

    logger.info(
        "Incidents found: artifact_id=%s failed_log_rows=%d newest_message_id=%s",
        artifact_id,
        len(logs),
        mid,
    )

    if has_message_id(mid):
        trace("Monitor: artifact=%s → skip (duplicate message_id in DB: %s)" % (artifact_id, mid))
        _record(
            artifact_id=artifact_id,
            message_guid=mid,
            skipped=True,
            skip_reason="duplicate_message_id_sqlite",
            analysis=None,
            error=None,
        )
        return "skipped_duplicate_message_id"

    pkg = (newest.get("package_id") or "").strip() or None
    trace("Monitor: artifact=%s  running full agent (run_investigation) message_id=%r …" % (artifact_id, mid))

    response = run_investigation(
        iflow_name=artifact_id,
        message_id=mid,
        error_message=(newest.get("error") or None),
        integration_package_id=pkg,
    )

    stored = insert_incident(
        message_id=mid,
        response=response,
        jira_ticket_id=None,
        investigation_status="completed",
    )

    logger.info(
        "Incident analysis completed: message_id=%s iflow=%s error_type=%s severity=%s confidence=%s stored=%s",
        mid,
        response.iflow,
        response.error_type,
        response.severity,
        response.confidence_score,
        stored,
    )

    _record(
        artifact_id=artifact_id,
        message_guid=mid,
        skipped=False,
        skip_reason=None,
        analysis=response.model_dump(),
        error=None,
    )
    trace(
        "Monitor: llm_analysis done  guid=%s  artifact=%s  error_type=%s  severity=%s  confidence=%s"
        % (mid, artifact_id, response.error_type, response.severity, response.confidence_score)
    )
    return "stored" if stored else "investigation_ran_incident_not_stored"


def _record(
    *,
    artifact_id: str,
    message_guid: str | None,
    skipped: bool,
    skip_reason: str | None,
    analysis: dict[str, Any] | None,
    error: str | None,
) -> None:
    row: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "artifact_id": artifact_id,
        "message_guid": message_guid,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "error": error,
    }
    if analysis:
        row.update(
            {
                "error_summary": analysis.get("error_summary"),
                "error_type": analysis.get("error_type"),
                "severity": analysis.get("severity"),
                "confidence_score": analysis.get("confidence_score"),
                "root_cause": analysis.get("root_cause"),
                "recommendation": analysis.get("recommendation"),
            }
        )
    _history.append(row)
    if len(_history) > _MAX_HISTORY * 2:
        del _history[: len(_history) - _MAX_HISTORY]


def start_monitor_scheduler() -> None:
    """Start APScheduler when ``SCHEDULER_ENABLED=true`` and CPI is not mocked."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    if not settings.scheduler_enabled:
        logger.info("Background CPI monitor disabled (SCHEDULER_ENABLED=false)")
        return
    if settings.cpi_use_mock:
        logger.warning("SCHEDULER_ENABLED=true but CPI_USE_MOCK=true — monitor not started")
        return

    _scheduler = BackgroundScheduler()
    # Default 300 s = 5 minutes (see ``scheduler_interval_sec`` in settings).
    interval = max(60, int(settings.scheduler_interval_sec))
    _scheduler.add_job(
        run_monitor_cycle,
        "interval",
        seconds=interval,
        id="cpi_failed_log_monitor",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    job = _scheduler.get_job("cpi_failed_log_monitor")
    nrt = job.next_run_time if job else None
    nrt_s = nrt.isoformat() if nrt is not None else "n/a"
    logger.info(
        "Started CPI monitor scheduler every %s seconds (next run at %s)",
        interval,
        nrt_s,
    )
    trace(
        "Scheduler: CPI monitor job started  interval_sec=%s  next_run=%s  MONITOR_IFLOW_IDS=%s"
        % (interval, nrt_s, monitored_artifact_ids())
    )


def stop_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Stopped CPI monitor scheduler")
    _scheduler = None
