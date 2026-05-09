"""
OpenRouter client — LLM inference with JSON-only responses.

Uses enriched CPI context built by the agent (logs + metadata + operator hints).
No LangChain: plain HTTP + prompt contract.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

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
- Base conclusions on the briefing; if unclear, use UNKNOWN and explain in root_cause
- evidence.logs_used / metadata_used reflect whether log/metadata sections contained usable facts
- agent_flow must list exactly those four steps in order
"""


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if m:
        return m.group(1).strip()
    return text


def analyze_with_openrouter(
    enriched_context: str,
    *,
    iflow_name: str,
    logs_used: bool,
    metadata_used: bool,
    brief_operator_hint: str | None = None,
) -> dict[str, Any]:
    """
    Send enriched context to OpenRouter; return parsed dict matching agent schema.

    Falls back to heuristic JSON if API key missing or request fails.
    """
    key = settings.effective_openrouter_key()
    base = settings.effective_openrouter_base()
    model = settings.openrouter_model

    user_prompt = (
        "Analyze the following CPI incident briefing and produce the JSON object.\n\n"
        f"BRIEFING:\n{enriched_context}\n\n"
        f"Internal hints (do not echo verbatim): logs_used_hint={logs_used}, metadata_used_hint={metadata_used}"
    )

    if not key:
        logger.info("OpenRouter API key not set — using heuristic agent output")
        return _heuristic_analysis(
            enriched_context,
            iflow_name=iflow_name,
            logs_used=logs_used,
            metadata_used=metadata_used,
            brief_operator_hint=brief_operator_hint,
        )

    url = f"{base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_http_referer,
        "X-Title": settings.openrouter_app_title,
    }

    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(url, headers=headers, json=payload)
        if r.status_code != 200:
            logger.warning("OpenRouter HTTP %s: %s", r.status_code, r.text[:800])
            return _heuristic_analysis(
                enriched_context,
                iflow_name=iflow_name,
                logs_used=logs_used,
                metadata_used=metadata_used,
                brief_operator_hint=brief_operator_hint,
            )
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        parsed = json.loads(_strip_json_fence(str(content)))
        return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenRouter call failed: %s", exc)
        return _heuristic_analysis(
            enriched_context,
            iflow_name=iflow_name,
            logs_used=logs_used,
            metadata_used=metadata_used,
            brief_operator_hint=brief_operator_hint,
        )


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
    return {
        "iflow": iflow_name,
        "error_summary": summary or "No summary — enable CPI logs or provide error_message.",
        "error_type": et,
        "severity": sev,
        "root_cause": root,
        "recommendation": rec,
        "evidence": {"logs_used": logs_used, "metadata_used": metadata_used},
        "agent_flow": ["fetch_logs", "fetch_metadata", "build_context", "llm_analysis"],
    }
