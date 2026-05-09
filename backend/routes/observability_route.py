"""Operator observability — join incidents SQLite, LLM audit, and in-memory monitor runs per error (MessageGuid)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from services.incidents_store import get_incident_by_message_id, list_incidents
from services.llm_audit_sqlite import list_exchanges_for_message_id
from services.monitor import get_monitor_history
from services.settings import settings

router = APIRouter(prefix="/observability", tags=["observability"])

# Mirrors ``agents.agent.AGENT_STEPS`` — shown in UI as the canonical pipeline before LLM audit rows.
AGENT_CANONICAL_STEPS: list[dict[str, str]] = [
    {
        "id": "fetch_logs",
        "title": "Fetch runtime logs",
        "detail": "CPI Message Processing Logs (MPL) for the integration artifact and MessageGuid.",
    },
    {
        "id": "fetch_metadata",
        "title": "Fetch iFlow metadata",
        "detail": "Design-time OData: artifact, configurations, resources, mapping hints.",
    },
    {
        "id": "build_context",
        "title": "Build briefing",
        "detail": "Single structured briefing (logs + metadata + operator error) for the model.",
    },
    {
        "id": "llm_analysis",
        "title": "LLM analysis",
        "detail": "OpenRouter JSON (or heuristic) — persisted in llm_audit.sqlite as llm_exchange rows.",
    },
]


def _monitor_runs_for_message(message_id: str) -> list[dict[str, Any]]:
    mid = (message_id or "").strip()
    if not mid:
        return []
    out: list[dict[str, Any]] = []
    for run in get_monitor_history():
        if (run.get("message_guid") or "").strip() == mid:
            out.append(run)
    return out


def _enrich_exchange_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    raw = r.get("response_json")
    if isinstance(raw, str) and raw.strip():
        try:
            r["response_obj"] = json.loads(raw)
        except json.JSONDecodeError:
            r["response_obj"] = None
    else:
        r["response_obj"] = None
    msgs = r.get("request_messages_json")
    if isinstance(msgs, str) and msgs.strip():
        try:
            r["request_messages"] = json.loads(msgs)
        except json.JSONDecodeError:
            r["request_messages"] = None
    else:
        r["request_messages"] = None
    return r


@router.get("/lifecycles")
def list_lifecycles(
    limit: int = Query(100, ge=1, le=500),
    exchange_limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    """
    Newest incidents first; each row includes matching LLM audit exchanges and in-memory monitor runs
    for that ``message_id``.
    """
    rows = list_incidents(limit=limit)
    incidents_out: list[dict[str, Any]] = []
    for inc in rows:
        mid = str(inc.get("message_id") or "")
        exchanges = [_enrich_exchange_row(x) for x in list_exchanges_for_message_id(mid, limit=exchange_limit)]
        incidents_out.append(
            {
                **inc,
                "llm_exchange_count": len(exchanges),
                "llm_exchanges": exchanges,
                "monitor_runs": _monitor_runs_for_message(mid),
            }
        )
    return {
        "incidents_sqlite_enabled": settings.incidents_sqlite_enabled,
        "llm_audit_sqlite_enabled": settings.llm_audit_sqlite_enabled,
        "agent_canonical_steps": AGENT_CANONICAL_STEPS,
        "incidents": incidents_out,
    }


@router.get("/lifecycle/{message_id}")
def get_lifecycle(message_id: str, exchange_limit: int = Query(80, ge=1, le=200)) -> dict[str, Any]:
    """Full detail for one MPL MessageGuid (URL-encode slashes if any — uncommon for GUIDs)."""
    mid = (message_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="message_id required")
    inc = get_incident_by_message_id(mid)
    if inc is None:
        raise HTTPException(status_code=404, detail="No incident row for this message_id")
    exchanges = [_enrich_exchange_row(x) for x in list_exchanges_for_message_id(mid, limit=exchange_limit)]
    return {
        "incident": inc,
        "agent_canonical_steps": AGENT_CANONICAL_STEPS,
        "llm_exchanges": exchanges,
        "monitor_runs": _monitor_runs_for_message(mid),
        "llm_audit_sqlite_enabled": settings.llm_audit_sqlite_enabled,
    }
