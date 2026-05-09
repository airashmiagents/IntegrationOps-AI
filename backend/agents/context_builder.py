"""
CONTEXT BUILDER — merges tool outputs into a single LLM briefing.

The LLM never sees an isolated raw error string without CPI evidence sections:
we always attach structured runtime logs and iFlow metadata when available.
"""

from __future__ import annotations

import json
from typing import Any


def build_context(
    *,
    iflow_name: str,
    message_id: str | None,
    operator_error: str | None,
    runtime_logs: list[dict[str, str]],
    iflow_metadata: dict[str, Any],
) -> str:
    """
    Merge CPI runtime logs, design-time metadata, and optional operator fallback.

    Returns one markdown-style structured string used as the sole user-visible
    incident briefing for the LLM (TOOL outputs + labeled fallback).
    """
    lines: list[str] = []
    lines.append("# AUTONOMOUS CPI INCIDENT BRIEFING")
    lines.append("")
    lines.append("## Target")
    lines.append(f"- iFlow: `{iflow_name}`")
    lines.append(f"- Message ID (if known): `{message_id or '(not provided)'}`")
    lines.append("")
    lines.append("## SECTION A — Runtime logs (Message Processing / adapter)")
    lines.append("Structured entries from CPI monitoring (tool: fetch_runtime_logs):")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(runtime_logs, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## SECTION B — iFlow artifact metadata")
    lines.append("Design-time summary (tool: fetch_iflow_metadata):")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(iflow_metadata, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## SECTION C — Operator-reported error (fallback signal)")
    if operator_error and operator_error.strip():
        lines.append(
            "Use only if logs are empty or ambiguous; corroborate with Sections A/B when possible:"
        )
        lines.append("")
        lines.append(operator_error.strip())
    else:
        lines.append("(none — rely on Sections A and B)")
    lines.append("")
    return "\n".join(lines)
