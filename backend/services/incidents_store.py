"""
Persist autonomous monitor investigations to SQLite (stdlib only).

Dedupe: UNIQUE(message_id) so the same MPL MessageGuid is never stored twice across restarts.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.schemas import AgentInvestigationResponse
from services.settings import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "incidents.sqlite"


def incidents_db_path() -> Path:
    raw = (settings.incidents_sqlite_path or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_PATH


def _apply_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            message_id TEXT NOT NULL UNIQUE,
            iflow TEXT NOT NULL,
            error_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            root_cause TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            jira_ticket_id TEXT,
            investigation_status TEXT NOT NULL DEFAULT 'completed'
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents(timestamp)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_incidents_iflow ON incidents(iflow)")


def init_incidents_db() -> None:
    if not settings.incidents_sqlite_enabled:
        return
    with _lock:
        path = incidents_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), check_same_thread=False)
        try:
            _apply_schema(con)
            con.commit()
        finally:
            con.close()
    logger.info("Incidents SQLite ready at %s", path)


def has_message_id(message_id: str) -> bool:
    """True if this MPL MessageGuid was already stored (duplicate incident)."""
    if not settings.incidents_sqlite_enabled or not (message_id or "").strip():
        return False
    mid = message_id.strip()
    with _lock:
        con = sqlite3.connect(str(incidents_db_path()), check_same_thread=False)
        try:
            _apply_schema(con)
            row = con.execute("SELECT 1 FROM incidents WHERE message_id = ? LIMIT 1", (mid,)).fetchone()
            return row is not None
        finally:
            con.close()


def insert_incident(
    *,
    message_id: str,
    response: AgentInvestigationResponse,
    jira_ticket_id: str | None = None,
    investigation_status: str = "completed",
) -> bool:
    """
    Insert one incident row. Returns True if inserted, False if message_id duplicate (INSERT OR IGNORE).
    """
    if not settings.incidents_sqlite_enabled:
        return False
    ts = datetime.now(timezone.utc).isoformat()
    mid = (message_id or "").strip()
    if not mid:
        return False
    jira = (jira_ticket_id or "").strip() or None
    status = (investigation_status or "completed").strip()[:64]

    with _lock:
        path = incidents_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), check_same_thread=False)
        try:
            _apply_schema(con)
            con.execute(
                """
                INSERT INTO incidents (
                    timestamp, message_id, iflow, error_type, severity,
                    root_cause, recommendation, confidence_score, jira_ticket_id, investigation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    mid,
                    response.iflow[:1024],
                    str(response.error_type),
                    str(response.severity),
                    response.root_cause[:16000],
                    response.recommendation[:16000],
                    int(response.confidence_score),
                    jira,
                    status,
                ),
            )
            con.commit()
            return True
        except sqlite3.IntegrityError:
            con.rollback()
            logger.debug("Incident skipped (duplicate message_id): %s", mid)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Incident insert failed: %s", exc)
            try:
                con.rollback()
            except Exception:
                pass
            return False
        finally:
            con.close()


def get_incident_by_message_id(message_id: str) -> dict[str, Any] | None:
    """Single incident row by MPL ``message_id``, or None."""
    if not settings.incidents_sqlite_enabled:
        return None
    mid = (message_id or "").strip()
    if not mid:
        return None
    with _lock:
        con = sqlite3.connect(str(incidents_db_path()), check_same_thread=False)
        try:
            _apply_schema(con)
            cur = con.execute(
                """
                SELECT id, timestamp, message_id, iflow, error_type, severity, root_cause,
                       recommendation, confidence_score, jira_ticket_id, investigation_status
                FROM incidents WHERE message_id = ? LIMIT 1
                """,
                (mid,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        finally:
            con.close()


def list_incidents(*, limit: int = 200) -> list[dict[str, Any]]:
    """Newest first for GET /incidents."""
    if not settings.incidents_sqlite_enabled:
        return []
    lim = max(1, min(500, int(limit)))
    with _lock:
        con = sqlite3.connect(str(incidents_db_path()), check_same_thread=False)
        try:
            _apply_schema(con)
            cur = con.execute(
                """
                SELECT id, timestamp, message_id, iflow, error_type, severity, root_cause,
                       recommendation, confidence_score, jira_ticket_id, investigation_status
                FROM incidents
                ORDER BY datetime(timestamp) DESC, id DESC
                LIMIT ?
                """,
                (lim,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()
