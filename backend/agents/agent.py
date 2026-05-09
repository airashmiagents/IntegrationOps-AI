"""
AUTONOMOUS SAP CPI INCIDENT INVESTIGATION AGENT

Orchestrates tool-style steps without LangChain:
  1. fetch_runtime_logs      → services.cpi_client
  2. fetch_iflow_metadata    → services.cpi_client
  3. build_context           → agents.context_builder
  4. llm_analysis            → services.ai_service (OpenRouter)

Returns enterprise-style structured JSON for dashboards and alerting.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.context_builder import build_context
from models.schemas import AgentEvidence, AgentInvestigationResponse, ErrorType, Severity
from services.ai_service import analyze_with_openrouter
from services.cpi_client import fetch_iflow_metadata, fetch_runtime_logs

logger = logging.getLogger(__name__)

AGENT_STEPS = ["fetch_logs", "fetch_metadata", "build_context", "llm_analysis"]


def run_investigation(
    *,
    iflow_name: str,
    message_id: str | None = None,
    error_message: str | None = None,
) -> AgentInvestigationResponse:
    """
    Run the full autonomous workflow and normalize output to the API contract.

    Each phase appends to agent_flow to make reasoning explicit to operators.
    """
    agent_flow: list[str] = []

    # --- TOOL STEP 1: CPI runtime logs ---
    logs = fetch_runtime_logs(iflow_name, message_id, error_fallback=error_message)
    agent_flow.append("fetch_logs")
    logs_used = bool(logs) and any(
        (e.get("error") or e.get("message_id") or e.get("adapter")) for e in logs
    )

    # --- TOOL STEP 2: iFlow metadata ---
    metadata = fetch_iflow_metadata(iflow_name)
    agent_flow.append("fetch_metadata")
    metadata_used = bool(metadata.get("endpoints") or metadata.get("adapters"))

    # --- CONTEXT BUILDER: single briefing for the LLM ---
    briefing = build_context(
        iflow_name=iflow_name,
        message_id=message_id,
        operator_error=error_message,
        runtime_logs=logs,
        iflow_metadata=metadata,
    )
    agent_flow.append("build_context")

    brief_hint = (error_message or "").strip()
    if not brief_hint and logs:
        brief_hint = next((e.get("error", "").strip() for e in logs if e.get("error")), "")[:500]

    # --- LLM STEP: OpenRouter (JSON mode) — model sees full briefing, not operator text alone ---
    raw_llm: dict[str, Any] = analyze_with_openrouter(
        briefing,
        iflow_name=iflow_name,
        logs_used=logs_used,
        metadata_used=metadata_used,
        brief_operator_hint=brief_hint or None,
    )
    agent_flow.append("llm_analysis")

    normalized = _normalize_llm_payload(
        raw_llm,
        iflow_name=iflow_name,
        logs_used=logs_used,
        metadata_used=metadata_used,
        agent_flow=agent_flow,
    )
    return normalized


def _coerce_error_type(value: Any) -> ErrorType:
    allowed = {"PKIX", "AUTH", "TIMEOUT", "MAPPING", "UNKNOWN"}
    s = str(value or "UNKNOWN").upper().strip()
    return s if s in allowed else "UNKNOWN"


def _coerce_severity(value: Any) -> Severity:
    allowed = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    s = str(value or "MEDIUM").upper().strip()
    return s if s in allowed else "MEDIUM"


def _normalize_llm_payload(
    raw: dict[str, Any],
    *,
    iflow_name: str,
    logs_used: bool,
    metadata_used: bool,
    agent_flow: list[str],
) -> AgentInvestigationResponse:
    """Ensure response matches enterprise JSON contract even if model drifts."""
    evidence_in = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    evidence = AgentEvidence(
        logs_used=bool(evidence_in.get("logs_used", logs_used)),
        metadata_used=bool(evidence_in.get("metadata_used", metadata_used)),
    )

    flow = raw.get("agent_flow")
    if not isinstance(flow, list) or [str(x) for x in flow] != AGENT_STEPS:
        flow_out = AGENT_STEPS.copy()
    else:
        flow_out = [str(x) for x in flow]

    iflow_out = str(raw.get("iflow") or iflow_name)

    return AgentInvestigationResponse(
        iflow=iflow_out,
        error_summary=str(raw.get("error_summary") or "No summary provided."),
        error_type=_coerce_error_type(raw.get("error_type")),
        severity=_coerce_severity(raw.get("severity")),
        root_cause=str(raw.get("root_cause") or ""),
        recommendation=str(raw.get("recommendation") or ""),
        evidence=evidence,
        agent_flow=flow_out,
    )
