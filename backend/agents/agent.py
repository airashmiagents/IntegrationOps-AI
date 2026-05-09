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
from services.agent_trace import summarize_iflow_metadata, summarize_runtime_logs, trace, trace_block
from services.ai_service import analyze_with_openrouter
from services.cpi_client import fetch_iflow_metadata, fetch_runtime_logs
from services.settings import settings

logger = logging.getLogger(__name__)

AGENT_STEPS = ["fetch_logs", "fetch_metadata", "build_context", "llm_analysis"]


def _metadata_informed(metadata: dict[str, Any]) -> bool:
    """True when design-time or derived fields give the LLM real integration context."""
    if metadata.get("endpoints") or metadata.get("adapters"):
        return True
    if metadata.get("designtime_artifact") and isinstance(metadata["designtime_artifact"], dict):
        return bool(metadata["designtime_artifact"])
    if metadata.get("configurations") and isinstance(metadata["configurations"], list):
        return len(metadata["configurations"]) > 0
    if metadata.get("resources") and isinstance(metadata["resources"], list):
        return len(metadata["resources"]) > 0
    if metadata.get("message_mapping_artifacts") and isinstance(metadata["message_mapping_artifacts"], list):
        return len(metadata["message_mapping_artifacts"]) > 0
    if metadata.get("mappings") and isinstance(metadata["mappings"], list):
        return len(metadata["mappings"]) > 0
    if metadata.get("resources_count") is not None:
        return True
    return False


def run_investigation(
    *,
    iflow_name: str,
    iflow_version: str | None = None,
    integration_package_id: str | None = None,
    message_id: str | None = None,
    error_message: str | None = None,
) -> AgentInvestigationResponse:
    """
    Run the full autonomous workflow and normalize output to the API contract.

    Each phase appends to agent_flow to make reasoning explicit to operators.
    """
    agent_flow: list[str] = []
    trace(
        "Investigation ▶ start  iflow=%r  message_id=%r  cpi_mock=%s"
        % (iflow_name, message_id, settings.cpi_use_mock)
    )

    # --- TOOL STEP 1: CPI runtime logs ---
    logs = fetch_runtime_logs(iflow_name, message_id, error_fallback=error_message)
    agent_flow.append("fetch_logs")
    logs_used = bool(logs) and any(
        (e.get("error") or e.get("message_id") or e.get("adapter")) for e in logs
    )
    trace("Step fetch_logs (MessageProcessingLogs / MPL) → " + summarize_runtime_logs(logs))

    # --- TOOL STEP 2: iFlow metadata (design-time OData: artifact, configurations, resources) ---
    pkg_from_logs = integration_package_id or next(
        (e.get("package_id") for e in logs if e.get("package_id")),
        None,
    )
    metadata = fetch_iflow_metadata(
        iflow_name,
        iflow_version=iflow_version,
        integration_package_id=pkg_from_logs,
    )
    agent_flow.append("fetch_metadata")
    metadata_used = _metadata_informed(metadata)
    trace("Step fetch_metadata (IntegrationDesigntimeArtifacts / configs / resources) → " + summarize_iflow_metadata(metadata))

    # --- CONTEXT BUILDER: single briefing for the LLM ---
    briefing = build_context(
        iflow_name=iflow_name,
        message_id=message_id,
        operator_error=error_message,
        runtime_logs=logs,
        iflow_metadata=metadata,
    )
    agent_flow.append("build_context")
    trace("Step build_context → briefing_chars=%s  logs_used=%s  metadata_used=%s" % (len(briefing), logs_used, metadata_used))
    trace_block("Briefing text sent into the LLM user message (enriched_context)", briefing)

    brief_hint = (error_message or "").strip()
    if not brief_hint and logs:
        brief_hint = next((e.get("error", "").strip() for e in logs if e.get("error")), "")[:500]

    # --- LLM STEP: OpenRouter (JSON mode) — model sees full briefing, not operator text alone ---
    raw_llm: dict[str, Any] = analyze_with_openrouter(
        briefing,
        iflow_name=iflow_name,
        message_id=message_id,
        logs_used=logs_used,
        metadata_used=metadata_used,
        brief_operator_hint=brief_hint or None,
    )
    agent_flow.append("llm_analysis")
    trace(
        "Step llm_analysis done → error_type=%s  severity=%s  confidence=%s  summary=%r"
        % (
            raw_llm.get("error_type"),
            raw_llm.get("severity"),
            raw_llm.get("confidence_score"),
            (str(raw_llm.get("error_summary") or "")[:160]),
        )
    )

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


def _coerce_confidence_score(value: Any, *, logs_used: bool, metadata_used: bool, error_type: ErrorType) -> int:
    """
    Normalize model output to an int in [0, 100].

    Reject bool (Python bool subclasses int) and non-numeric junk. When the model omits the field or returns
    something unparseable, derive a conservative score from evidence strength so the API always exposes a stable
    integer aligned with the prompt bands (high = strong logs+metadata, low = UNKNOWN or weak signals).
    """
    # bool subclasses int in Python — normalize booleans away before numeric checks.
    if isinstance(value, bool):
        value = None
    if value is not None:
        try:
            if isinstance(value, int):
                return max(0, min(100, value))
            if isinstance(value, float):
                return max(0, min(100, int(round(value))))
            if isinstance(value, str) and value.strip():
                return max(0, min(100, int(round(float(value.strip())))))
        except (ValueError, TypeError):
            pass

    strength = int(logs_used) + int(metadata_used)
    if error_type == "UNKNOWN":
        return max(0, min(100, 28 + strength * 11))
    if strength >= 2:
        return 58
    if strength == 1:
        return 48
    return 38


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
    et = _coerce_error_type(raw.get("error_type"))
    confidence = _coerce_confidence_score(
        raw.get("confidence_score"),
        logs_used=evidence.logs_used,
        metadata_used=evidence.metadata_used,
        error_type=et,
    )

    return AgentInvestigationResponse(
        iflow=iflow_out,
        error_summary=str(raw.get("error_summary") or "No summary provided."),
        error_type=et,
        severity=_coerce_severity(raw.get("severity")),
        confidence_score=confidence,
        root_cause=str(raw.get("root_cause") or ""),
        recommendation=str(raw.get("recommendation") or ""),
        evidence=evidence,
        agent_flow=flow_out,
    )
