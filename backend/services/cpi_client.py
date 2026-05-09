"""
SAP CPI integration layer — OData monitoring calls with mock fallback.

TOOL STEP 1 & 2 for the autonomous agent:
  - Runtime message processing logs (errors, adapters, components)
  - iFlow artifact metadata (endpoints, adapters, security, mappings)

When CPI_USE_MOCK=true or credentials/network fail, responses are deterministic
mock payloads so the agent workflow still demos end-to-end.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from services.settings import settings

logger = logging.getLogger(__name__)

def _mpl_path() -> str:
    """Message Processing Logs OData path — from settings so .env can override 404s."""
    p = (settings.sap_cpi_mpl_path or "/http/v1/MessageProcessingLogs").strip()
    return p if p.startswith("/") else f"/{p}"


def _normalize_log_entry(raw: dict[str, Any]) -> dict[str, str]:
    """Map heterogeneous CPI/API keys into our stable agent contract."""
    return {
        "timestamp": str(raw.get("timestamp") or raw.get("LogStart") or raw.get("StartTime") or ""),
        "error": str(raw.get("error") or raw.get("Error") or raw.get("LastErrorModel") or ""),
        "message_id": str(raw.get("message_id") or raw.get("MessageGuid") or raw.get("MessageID") or ""),
        "adapter": str(raw.get("adapter") or raw.get("SenderAdapter") or raw.get("Adapter") or ""),
        "component": str(raw.get("component") or raw.get("Component") or raw.get("IntegrationFlow") or ""),
    }


def _mock_runtime_logs(iflow_name: str, message_id: str | None, error_hint: str) -> list[dict[str, str]]:
    """Simulated CPI runtime errors — grounded in iflow / operator hint for demos."""
    mid = message_id or "MOCK-CPI-MSG-88421"
    err = error_hint or "javax.net.ssl.SSLHandshakeException: PKIX path building failed"
    return [
        {
            "timestamp": "2026-05-09T14:22:01.003Z",
            "error": err[:2000],
            "message_id": mid,
            "adapter": "HTTPS",
            "component": f"{iflow_name}_ReceiverChannel",
        },
        {
            "timestamp": "2026-05-09T14:22:00.512Z",
            "error": "Target endpoint handshake failed — certificate chain validation error",
            "message_id": mid,
            "adapter": "HTTPS",
            "component": "ExternalCall",
        },
    ]


def _mock_iflow_metadata(iflow_name: str) -> dict[str, Any]:
    """Simulated design-time summary — endpoints, adapters, security, mappings."""
    return {
        "iflow_name": iflow_name,
        "endpoints": [
            f"/{iflow_name}/v1/process",
            "https://partner.example.com/api/v2/orders",
        ],
        "adapters": ["HTTPS (sender)", "HTTPS (receiver)", "JSON/XML converter"],
        "security": "OAuth2 client credentials + TLS mutual-auth optional",
        "mappings": [
            "OrderCanonical → PartnerOrder_v2.xslt",
            "Fault handler → GenericErrorResponse.mapping",
        ],
    }


def _odata_string(value: str) -> str:
    """Escape single quotes for OData string literals (' → '')."""
    return value.replace("'", "''")


def _try_fetch_logs_odata(base: str, user: str, password: str, iflow_name: str, message_id: str | None) -> list[dict[str, str]] | None:
    """
    Attempt real CPI OData query for MessageProcessingLogs.

    Uses JSON when the tenant supports it; returns None on any failure
    so the caller can fall back to mock data.
    """
    url = base.rstrip("/") + _mpl_path()
    params: dict[str, str] = {"$format": "json", "$top": "20"}
    # OData filter varies by tenant version; keep filter minimal for portability.
    safe_flow = _odata_string(iflow_name)
    filt_parts = [f"IntegrationFlow eq '{safe_flow}'"]
    if message_id:
        filt_parts.append(f"MessageGuid eq '{_odata_string(message_id)}'")
    params["$filter"] = " and ".join(filt_parts)

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, params=params, auth=(user, password), headers={"Accept": "application/json"})
        if r.status_code != 200:
            logger.warning("CPI OData logs HTTP %s: %s", r.status_code, r.text[:500])
            return None
        payload = r.json()
        rows = payload.get("d", {}).get("results") if isinstance(payload.get("d"), dict) else None
        if rows is None and isinstance(payload.get("value"), list):
            rows = payload["value"]
        if not rows:
            return []
        out: list[dict[str, str]] = []
        for row in rows:
            if isinstance(row, dict):
                out.append(_normalize_log_entry(row))
        return out
    except Exception as exc:  # noqa: BLE001 — degrade to mock on any integration issue
        logger.warning("CPI OData logs fetch failed: %s", exc)
        return None


def fetch_runtime_logs(
    iflow_name: str,
    message_id: str | None = None,
    *,
    error_fallback: str | None = None,
) -> list[dict[str, str]]:
    """
    TOOL STEP 1 — Fetch CPI runtime error logs for an iFlow.

    Returns a list of structured log entries:
      timestamp, error, message_id, adapter, component
    """
    if settings.cpi_use_mock:
        return _mock_runtime_logs(iflow_name, message_id, error_fallback or "")

    base = settings.sap_cpi_base_url.strip()
    user = settings.sap_cpi_user
    password = settings.sap_cpi_password
    if not base or not user:
        logger.info("CPI mock: missing base URL or user — using simulated logs")
        return _mock_runtime_logs(iflow_name, message_id, error_fallback or "")

    fetched = _try_fetch_logs_odata(base, user, password, iflow_name, message_id)
    if fetched is None:
        return _mock_runtime_logs(iflow_name, message_id, error_fallback or "")
    if not fetched and error_fallback:
        # OData succeeded but empty — still give operator hint into context via synthetic row.
        return [
            {
                "timestamp": "",
                "error": error_fallback[:2000],
                "message_id": message_id or "",
                "adapter": "",
                "component": iflow_name,
            }
        ]
    return fetched


def fetch_iflow_metadata(iflow_name: str) -> dict[str, Any]:
    """
    TOOL STEP 2 — Fetch iFlow artifact details (endpoints, adapters, security, mappings).

    Real CPI design-time APIs differ by landscape; we return mock metadata unless
    a future implementation wires Integration Designer OData.
    """
    if settings.cpi_use_mock:
        return _mock_iflow_metadata(iflow_name)

    base = settings.sap_cpi_base_url.strip()
    user = settings.sap_cpi_user
    password = settings.sap_cpi_password
    if not base or not user:
        return _mock_iflow_metadata(iflow_name)

    # Optional stub for package artifact lookup — keeps structure enterprise-like without brittle XML OData here.
    artifact_url = base.rstrip("/") + f"/api/v1/IntegrationRuntimeArtifacts('{iflow_name}')"
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.get(
                artifact_url,
                headers={"Accept": "application/json"},
                auth=(user, password),
            )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                return {
                    "iflow_name": str(data.get("Id") or data.get("Name") or iflow_name),
                    "endpoints": list(data.get("endpoints") or []) or _mock_iflow_metadata(iflow_name)["endpoints"],
                    "adapters": list(data.get("adapters") or []) or _mock_iflow_metadata(iflow_name)["adapters"],
                    "security": str(data.get("security") or _mock_iflow_metadata(iflow_name)["security"]),
                    "mappings": list(data.get("mappings") or []) or _mock_iflow_metadata(iflow_name)["mappings"],
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("CPI metadata fetch failed, using mock: %s", exc)

    return _mock_iflow_metadata(iflow_name)


def logs_and_metadata_snapshot(iflow_name: str, message_id: str | None, error_fallback: str | None) -> str:
    """Debug helper — JSON preview for logs/troubleshooting."""
    return json.dumps(
        {
            "logs": fetch_runtime_logs(iflow_name, message_id, error_fallback=error_fallback),
            "metadata": fetch_iflow_metadata(iflow_name),
        },
        indent=2,
    )
