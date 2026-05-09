"""
Append-only SQLite log of LLM requests (system + user as sent to the API) and responses.

Hackathon-friendly: stdlib sqlite3, optional via settings. One row per exchange (including
failed OpenRouter attempts so operators can debug HTTP/parse errors).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.settings import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# Log "ready" once per DB path (schema may be reapplied many times; that is cheap and fixes empty shell-created files).
_ready_logged: set[str] = set()

# Default file lives next to the app when cwd is ``backend/`` (typical uvicorn).
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "llm_audit.sqlite"


def audit_db_path() -> Path:
    raw = (settings.llm_audit_sqlite_path or "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_DB_PATH


def _apply_schema(con: sqlite3.Connection) -> None:
    """Idempotent DDL — safe if ``llm_audit.sqlite`` already existed as an empty file from the shell."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_exchange (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            iflow_name TEXT,
            message_id TEXT,
            exchange_path TEXT NOT NULL,
            model TEXT,
            http_status INTEGER,
            request_messages_json TEXT NOT NULL,
            raw_assistant_text TEXT,
            response_json TEXT NOT NULL,
            error_note TEXT
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_llm_exchange_created ON llm_exchange(created_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_llm_exchange_iflow ON llm_exchange(iflow_name)")
    _ensure_llm_exchange_message_id_column(con)


def _ensure_llm_exchange_message_id_column(con: sqlite3.Connection) -> None:
    """Append ``message_id`` for correlating audit rows to MPL MessageGuid / incidents (existing DBs)."""
    cur = con.execute("PRAGMA table_info(llm_exchange)")
    cols = {str(r[1]) for r in cur.fetchall()}
    if "message_id" not in cols:
        con.execute("ALTER TABLE llm_exchange ADD COLUMN message_id TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_llm_exchange_message_id ON llm_exchange(message_id)")


def init_llm_audit_db() -> None:
    """Create table and indexes if missing (idempotent)."""
    if not settings.llm_audit_sqlite_enabled:
        return
    with _lock:
        path = audit_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), check_same_thread=False)
        try:
            _apply_schema(con)
            con.commit()
        finally:
            con.close()
        key = str(path.resolve())
        if key not in _ready_logged:
            logger.info("LLM audit SQLite ready at %s", path)
            _ready_logged.add(key)


def log_llm_exchange(
    *,
    iflow_name: str,
    exchange_path: str,
    model: str | None,
    http_status: int | None,
    request_messages: list[dict[str, Any]],
    raw_assistant_text: str | None,
    response_obj: dict[str, Any] | None,
    error_note: str | None = None,
    message_id: str | None = None,
) -> None:
    """
    Persist one row: exact ``messages`` array sent to chat/completions (or same shape for
    heuristic audits), optional raw model string, and final ``response_obj`` as JSON
    (heuristic output when no provider text exists).
    """
    if not settings.llm_audit_sqlite_enabled:
        return
    created = datetime.now(timezone.utc).isoformat()
    response_json = json.dumps(response_obj if response_obj is not None else {}, ensure_ascii=False)
    req_json = json.dumps(request_messages, ensure_ascii=False)
    err = (error_note or "")[:16000] or None
    raw = raw_assistant_text if raw_assistant_text is not None else None
    if raw is not None and len(raw) > 1_000_000:
        raw = raw[:1_000_000] + "\n… (truncated)"
    mid = (message_id or "").strip()[:512] or None

    with _lock:
        path = audit_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), check_same_thread=False)
        try:
            _apply_schema(con)
            con.execute(
                """
                INSERT INTO llm_exchange (
                    created_at, iflow_name, message_id, exchange_path, model, http_status,
                    request_messages_json, raw_assistant_text, response_json, error_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created,
                    iflow_name[:512] if iflow_name else None,
                    mid,
                    exchange_path[:128],
                    model[:512] if model else None,
                    http_status,
                    req_json,
                    raw,
                    response_json,
                    err,
                ),
            )
            con.commit()
        except Exception as exc:  # noqa: BLE001 — never break the agent on audit failure
            logger.warning("LLM audit insert failed: %s", exc)
        finally:
            con.close()


def list_exchanges_for_message_id(message_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """
    Rows from ``llm_exchange`` for one MPL MessageGuid.

    Matches explicit ``message_id`` column when set; falls back to ``instr`` on
    ``request_messages_json`` for legacy rows (briefing embeds the GUID).
    """
    if not settings.llm_audit_sqlite_enabled:
        return []
    mid = (message_id or "").strip()
    if not mid:
        return []
    lim = max(1, min(200, int(limit)))
    with _lock:
        con = sqlite3.connect(str(audit_db_path()), check_same_thread=False)
        try:
            _apply_schema(con)
            cur = con.execute(
                """
                SELECT id, created_at, iflow_name, message_id, exchange_path, model, http_status,
                       request_messages_json, raw_assistant_text, response_json, error_note
                FROM llm_exchange
                WHERE (message_id IS NOT NULL AND message_id = ?)
                   OR (COALESCE(message_id, '') = '' AND instr(request_messages_json, ?) > 0)
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (mid, mid, lim),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()
