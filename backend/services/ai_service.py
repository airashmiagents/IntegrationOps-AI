"""
OpenRouter client — LLM inference with JSON-only responses.

Uses enriched CPI context built by the agent (logs + metadata + operator hints).
No LangChain: plain HTTP + prompt contract.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from services.agent_trace import trace, trace_llm_outcome
from services.llm_audit_sqlite import log_llm_exchange
from services.settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AUTONOMOUS SAP CPI INCIDENT INVESTIGATION AGENT.

You receive ONLY a structured briefing (runtime logs, iFlow metadata, optional operator error).
You MUST respond with a single JSON object — no markdown fences, no prose outside JSON.

Required JSON shape:
{
  "iflow": "<string>",
  "error_summary": "<string>",
  "error_type": "PKIX | AUTH | TIMEOUT | MAPPING | UNKNOWN",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "confidence_score": <integer 0-100 inclusive, JSON number not string>,
  "root_cause": "<string>",
  "recommendation": "<string>",
  "evidence": {
      "logs_used": <true|false>,
      "metadata_used": <true|false>
  },
  "agent_flow": ["fetch_logs", "fetch_metadata", "build_context", "llm_analysis"]
}

Rules:
- error_type must be exactly one of: PKIX, AUTH, TIMEOUT, MAPPING, UNKNOWN
- severity must be exactly one of: LOW, MEDIUM, HIGH, CRITICAL
- confidence_score MUST be a single JSON integer from 0 to 100 (never a float string like "85.0" as text; use 85)
- Base conclusions on the briefing; if unclear, use UNKNOWN and explain in root_cause
- evidence.logs_used / metadata_used reflect whether log/metadata sections contained usable facts
- agent_flow must list exactly those four steps in order

Confidence scoring (calibrate confidence_score to evidence strength, not model self-belief):
- High (80-100): Classic CPI signals with matching evidence — e.g. PKIX / SSLHandshake / certificate chain in logs
  aligned with error_type PKIX; HTTP 401/403/OAuth failures with clear MPL text for AUTH; explicit timeout errors
  with adapter and timestamps for TIMEOUT. Prefer high scores only when runtime logs AND/OR rich metadata clearly
  support the chosen error_type and root_cause.
- Medium (50-79): Partial or mixed evidence — sparse MPL lines, generic errors, or metadata_used but logs_used
  weak (or vice versa); reasonable inference but not airtight.
- Low (0-49): UNKNOWN error_type, vague "Internal Server Error", missing MessageGuid context, empty or contradictory
  sections, or conclusion not well supported by the briefing — score low even if you guess a category.
"""


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if m:
        return m.group(1).strip()
    return text


def _chat_messages_for_audit(user_prompt: str) -> list[dict[str, str]]:
    """Exact system + user texts sent to OpenRouter (used for SQLite audit rows)."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


@dataclass
class OpenRouterCallResult:
    """Outcome of one chat/completions POST — parsed dict if valid JSON, else diagnostics."""

    parsed: dict[str, Any] | None
    raw_assistant_text: str | None
    http_status: int | None
    error_note: str | None


def _openrouter_chat_json(
    *,
    url: str,
    headers: dict[str, str],
    model: str,
    user_prompt: str,
) -> OpenRouterCallResult:
    """Single chat/completions call; parsed JSON or None with HTTP / parse error notes."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": _chat_messages_for_audit(user_prompt),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    raw: str | None = None
    status: int | None = None
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(url, headers=headers, json=payload)
        status = r.status_code
        if r.status_code != 200:
            logger.warning("OpenRouter model=%s HTTP %s: %s", model, r.status_code, r.text[:800])
            return OpenRouterCallResult(None, None, status, r.text[:8000])
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            raw = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        else:
            raw = str(content)
        parsed = json.loads(_strip_json_fence(raw))
        return OpenRouterCallResult(parsed, raw, status, None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenRouter model=%s failed: %s", model, exc)
        return OpenRouterCallResult(None, raw, status, str(exc)[:8000])


def analyze_with_openrouter(
    enriched_context: str,
    *,
    iflow_name: str,
    message_id: str | None = None,
    logs_used: bool,
    metadata_used: bool,
    brief_operator_hint: str | None = None,
) -> dict[str, Any]:
    """
    Send enriched context to OpenRouter; return parsed dict matching agent schema.

    Tries ``openrouter_model`` first, then ``openrouter_fallback_model`` when set and distinct.
    Falls back to heuristic JSON if API key missing or all model attempts fail.
    """
    key = settings.effective_openrouter_key()
    base = settings.effective_openrouter_base()

    user_prompt = (
        "Analyze the following CPI incident briefing and produce the JSON object.\n\n"
        f"BRIEFING:\n{enriched_context}\n\n"
        "Include confidence_score as a JSON integer from 0 to 100 (not quoted, not float).\n\n"
        f"Internal hints (do not echo verbatim): logs_used_hint={logs_used}, metadata_used_hint={metadata_used}"
    )

    if not key:
        logger.info("OpenRouter API key not set — using heuristic agent output")
        result = _heuristic_analysis(
            enriched_context,
            iflow_name=iflow_name,
            logs_used=logs_used,
            metadata_used=metadata_used,
            brief_operator_hint=brief_operator_hint,
        )
        log_llm_exchange(
            iflow_name=iflow_name,
            exchange_path="heuristic_no_api_key",
            model=None,
            http_status=None,
            request_messages=_chat_messages_for_audit(user_prompt),
            raw_assistant_text=None,
            response_obj=result,
            error_note="OpenRouter API key not configured",
            message_id=message_id,
        )
        trace("OpenRouter: no API key → heuristic structured output")
        trace_llm_outcome(path="heuristic_no_api_key", model=None, payload=result)
        return result

    url = f"{base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_http_referer,
        "X-Title": settings.openrouter_app_title,
    }

    primary = (settings.openrouter_model or "").strip()
    fb_raw = (settings.openrouter_fallback_model or "").strip()
    models: list[str] = []
    if primary:
        models.append(primary)
    if fb_raw and fb_raw != primary and fb_raw not in models:
        models.append(fb_raw)

    trace(
        "OpenRouter: POST chat/completions  models=%r  user_prompt_chars=%s  iflow=%r"
        % (models, len(user_prompt), iflow_name)
    )

    msgs = _chat_messages_for_audit(user_prompt)
    for i, model in enumerate(models):
        path = "openrouter_primary" if i == 0 else "openrouter_fallback"
        res = _openrouter_chat_json(url=url, headers=headers, model=model, user_prompt=user_prompt)
        if res.parsed is not None:
            log_llm_exchange(
                iflow_name=iflow_name,
                exchange_path=path,
                model=model,
                http_status=res.http_status,
                request_messages=msgs,
                raw_assistant_text=res.raw_assistant_text,
                response_obj=res.parsed,
                error_note=None,
                message_id=message_id,
            )
            if i > 0:
                logger.info("OpenRouter succeeded with fallback model=%s", model)
            trace_llm_outcome(path="openrouter_json", model=model, payload=res.parsed)
            return res.parsed
        log_llm_exchange(
            iflow_name=iflow_name,
            exchange_path=path + "_failed",
            model=model,
            http_status=res.http_status,
            request_messages=msgs,
            raw_assistant_text=res.raw_assistant_text,
            response_obj={},
            error_note=res.error_note,
            message_id=message_id,
        )
        if i == 0 and len(models) > 1:
            logger.warning("OpenRouter primary model=%s failed — retrying fallback model=%s", primary, models[1])

    result = _heuristic_analysis(
        enriched_context,
        iflow_name=iflow_name,
        logs_used=logs_used,
        metadata_used=metadata_used,
        brief_operator_hint=brief_operator_hint,
    )
    log_llm_exchange(
        iflow_name=iflow_name,
        exchange_path="heuristic_after_openrouter_fail",
        model=None,
        http_status=None,
        request_messages=msgs,
        raw_assistant_text=None,
        response_obj=result,
        error_note="All OpenRouter model attempts failed; heuristic output returned",
        message_id=message_id,
    )
    trace("OpenRouter: all configured models failed → heuristic structured output")
    trace_llm_outcome(path="heuristic_after_openrouter_fail", model=None, payload=result)
    return result


def _heuristic_confidence(
    error_type: str,
    *,
    logs_used: bool,
    metadata_used: bool,
    brief_operator_hint: str | None,
) -> int:
    """
    Offline confidence: same rubric as the LLM prompt, simplified for keyword routing.

    Strong known patterns (PKIX/AUTH) plus structured logs or a clear operator hint → high band.
    TIMEOUT/MAPPING with weaker single-source evidence → medium.
    UNKNOWN or vague text with little corroboration → low.
    """
    hint = (brief_operator_hint or "").strip()
    hint_strong = len(hint) >= 24
    both_evidence = logs_used and metadata_used
    one_evidence = logs_used or metadata_used

    if error_type in ("PKIX", "AUTH"):
        if (logs_used and hint_strong) or both_evidence:
            return 85
        if logs_used or hint_strong or metadata_used:
            return 70
        return 55
    if error_type in ("TIMEOUT", "MAPPING"):
        if both_evidence:
            return 68
        if one_evidence:
            return 58
        return 48
    # UNKNOWN — align with "low confidence" band when the heuristic cannot classify.
    if one_evidence:
        return 38
    return 22


def _heuristic_analysis(
    text: str,
    *,
    iflow_name: str,
    logs_used: bool,
    metadata_used: bool,
    brief_operator_hint: str | None,
) -> dict[str, Any]:
    """Offline-safe structured output when LLM is unavailable."""
    upper = (brief_operator_hint or text).upper()
    if "PKIX" in upper or "CERTIFICATE" in upper or "SSLHANDSHAKE" in upper:
        et = "PKIX"
        sev = "HIGH"
        root = "TLS certificate validation failed — trust chain or hostname mismatch likely."
        rec = "Import partner root/intermediate into CPI keystore or fix server certificate; verify hostname/SNI."
    elif "401" in upper or "403" in upper or "UNAUTHORIZED" in upper or "OAUTH" in upper:
        et = "AUTH"
        sev = "HIGH"
        root = "Authentication or authorization rejected at receiver or token endpoint."
        rec = "Validate OAuth client credentials, scopes, and user roles; replay token retrieval outside CPI."
    elif "TIMEOUT" in upper or "TIMED OUT" in upper:
        et = "TIMEOUT"
        sev = "MEDIUM"
        root = "Downstream latency or network blockage caused adapter timeout."
        rec = "Increase HTTP timeout, verify endpoint availability, check firewall/DNS."
    elif "MAPPING" in upper or ("XML" in upper and "PARSING" in upper):
        et = "MAPPING"
        sev = "MEDIUM"
        root = "Payload transformation or parsing failed versus expected schema."
        rec = "Validate mapping artifacts and sample payloads against XSD/WSDL."
    else:
        et = "UNKNOWN"
        sev = "MEDIUM"
        root = "Insufficient signal in briefing — gather Message Processing Log details and payload snapshot."
        rec = "Enable trace on failing step and capture MPL attachments for mapping/security review."

    hint = (brief_operator_hint or "").strip()
    summary = hint[:280] if hint else text.replace("\n", " ")[:280]
    confidence = _heuristic_confidence(
        et, logs_used=logs_used, metadata_used=metadata_used, brief_operator_hint=brief_operator_hint
    )
    return {
        "iflow": iflow_name,
        "error_summary": summary or "No summary — enable CPI logs or provide error_message.",
        "error_type": et,
        "severity": sev,
        "confidence_score": confidence,
        "root_cause": root,
        "recommendation": rec,
        "evidence": {"logs_used": logs_used, "metadata_used": metadata_used},
        "agent_flow": ["fetch_logs", "fetch_metadata", "build_context", "llm_analysis"],
    }
