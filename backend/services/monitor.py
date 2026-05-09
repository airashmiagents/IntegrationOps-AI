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


def get_monitor_history() -> list[dict[str, Any]]:
    """Last N scheduler / manual runs (newest first)."""
    return list(reversed(_history[-_MAX_HISTORY :]))


def run_monitor_cycle(*, force: bool = False) -> None:
    """
    One poll: for each configured artifact Id, pull recent FAILED MPL rows, skip duplicates
    (``message_id`` already in ``incidents`` SQLite), then run the full investigation agent.
    """
    if not force and not settings.scheduler_enabled:
        return
    if settings.cpi_use_mock:
        logger.debug("Monitor cycle skipped: CPI_USE_MOCK=true")
        return

    ids = monitored_artifact_ids()
    if not ids:
        logger.warning("Monitor enabled but MONITOR_IFLOW_IDS is empty — nothing to poll")
        return

    logger.info("Monitoring cycle started — %d artifact(s): %s", len(ids), ids)
    trace(
        "Monitor cycle ▶  force=%s  artifact_ids=%s  lookback_min=%s  cpi_mock=%s"
        % (force, ids, settings.scheduler_lookback_minutes, settings.cpi_use_mock)
    )

    for aid in ids:
        try:
            _process_one_artifact(aid)
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


def _process_one_artifact(artifact_id: str) -> None:
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
        return

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
        return

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
        return

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
