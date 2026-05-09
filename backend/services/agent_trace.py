"""Optional step-by-step terminal narrative for investigations (see ``AGENT_TERMINAL_TRACE``)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from services.settings import settings

LOG = logging.getLogger("integrationops.agent")

_configured = False


def configure_terminal_trace_logging() -> None:
    """
    When ``AGENT_TERMINAL_TRACE`` is true, ensure trace lines always reach stderr even if
    the root logger is quieter than INFO (common with uvicorn defaults).
    """
    global _configured
    if not settings.agent_terminal_trace or _configured:
        return
    _configured = True
    LOG.setLevel(logging.INFO)
    if not LOG.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(levelname)s [agent-trace] %(message)s"))
        LOG.addHandler(h)
    LOG.propagate = False


def trace(msg: str) -> None:
    if settings.agent_terminal_trace:
        LOG.info("%s", msg)


def trace_block(title: str, body: str, *, max_chars: int = 2400, line_cap: int = 600) -> None:
    """Log a multi-line block with a title (each line prefixed for readability in terminals)."""
    if not settings.agent_terminal_trace:
        return
    LOG.info("%s", title)
    snippet = body if len(body) <= max_chars else body[:max_chars] + "\n… (truncated)"
    for raw_line in snippet.splitlines():
        line = raw_line if len(raw_line) <= line_cap else raw_line[: line_cap - 3] + "..."
        LOG.info("  %s", line)


def summarize_runtime_logs(logs: list[dict[str, Any]]) -> str:
    if not logs:
        return "no log rows"
    first = logs[0]
    err_preview = (first.get("error") or "")[:120].replace("\n", " ")
    return (
        f"rows={len(logs)}, newest_message_id={first.get('message_id')!r}, "
        f"package_id={first.get('package_id')!r}, error_preview={err_preview!r}"
    )


def summarize_iflow_metadata(metadata: dict[str, Any]) -> str:
    parts: list[str] = []
    da = metadata.get("designtime_artifact")
    if isinstance(da, dict) and da:
        parts.append(f"designtime_artifact.Id={da.get('Id')!r}")
    if metadata.get("resources_count") is not None:
        parts.append(f"resources_count={metadata.get('resources_count')}")
    for key in ("resources", "configurations", "endpoints", "adapters", "mappings"):
        v = metadata.get(key)
        if isinstance(v, list):
            parts.append(f"{key}={len(v)}")
    return ", ".join(parts) if parts else "(minimal or empty metadata)"


def trace_llm_outcome(*, path: str, model: str | None, payload: dict[str, Any]) -> None:
    if not settings.agent_terminal_trace:
        return
    slim = {
        "path": path,
        "model": model,
        "error_type": payload.get("error_type"),
        "severity": payload.get("severity"),
        "confidence_score": payload.get("confidence_score"),
        "error_summary": payload.get("error_summary"),
        "root_cause": payload.get("root_cause"),
        "recommendation": payload.get("recommendation"),
        "evidence": payload.get("evidence"),
    }
    LOG.info("LLM outcome (%s): %s", path, json.dumps(slim, ensure_ascii=False)[:2000])
