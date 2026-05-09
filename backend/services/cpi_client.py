"""
SAP CPI integration layer — OData monitoring calls with mock fallback.

URL layout follows SAP’s published Swagger for Integration Content and Message
Processing Logs (OData v2, Basic auth): tenant host + ``/api/v1/`` + entity set.
Legacy ``/http/v1`` tenants can set ``SAP_CPI_MPL_PATH`` / ``SAP_CPI_API_ROOT`` in ``.env``.

TOOL STEP 1 & 2 for the autonomous agent:
  - Runtime: ``MessageProcessingLogs`` (filter uses ``IntegrationArtifact/Id`` per spec)
  - Design-time: ``IntegrationDesigntimeArtifacts`` (+ Configurations, Resources); Version ``active`` supported

When CPI_USE_MOCK=true or credentials/network fail, responses are deterministic
mock payloads so the agent workflow still demos end-to-end.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from services.settings import settings

logger = logging.getLogger(__name__)


def _normalize_tenant_base(base: str) -> str:
    """
    Swagger expects host + ``/api/v1/...`` as separate segments.

    If operators paste ``...ondemand.com/api/v1`` into SAP_CPI_BASE_URL, strip the suffix
    so we do not double-append ``/api/v1``.
    """
    b = base.strip().rstrip("/")
    for suf in ("/api/v1", "/cpi/api/v1"):
        if b.lower().endswith(suf.lower()):
            return b[: -len(suf)].rstrip("/")
    return b


def _api_root() -> str:
    """Shared REST prefix for MPL and Integration Content APIs (see SAP CPI Swagger)."""
    r = (settings.sap_cpi_api_root or "/api/v1").strip().rstrip("/")
    return r if r.startswith("/") else f"/{r}"


def _mpl_path() -> str:
    """Message Processing Logs path: override, else ``{api_root}/MessageProcessingLogs``."""
    custom = (settings.sap_cpi_mpl_path or "").strip()
    if custom:
        return custom if custom.startswith("/") else f"/{custom}"
    return f"{_api_root()}/MessageProcessingLogs"


def _integration_artifact_id(raw: dict[str, Any]) -> str:
    """SAP MPL v1 nests flow id under ``IntegrationArtifact``."""
    ia = raw.get("IntegrationArtifact")
    if isinstance(ia, dict):
        return str(ia.get("Id") or "")
    return ""


def _integration_package_id(raw: dict[str, Any]) -> str:
    """MPL ``IntegrationArtifact.PackageId`` — disambiguates duplicate artifact Ids across packages."""
    ia = raw.get("IntegrationArtifact")
    if isinstance(ia, dict) and ia.get("PackageId"):
        return str(ia.get("PackageId"))
    return ""


def _normalize_log_entry(raw: dict[str, Any]) -> dict[str, str]:
    """Map CPI MessageProcessingLog rows (Swagger) into our stable agent contract."""
    ia_id = _integration_artifact_id(raw)
    pkg_id = _integration_package_id(raw)
    err = raw.get("error") or raw.get("Error") or raw.get("LastErrorModel") or ""
    if not err:
        st = raw.get("Status") or raw.get("CustomStatus")
        if st:
            err = f"Status={st}"
    sender = raw.get("Sender")
    receiver = raw.get("Receiver")
    adapter = str(sender or receiver or raw.get("SenderAdapter") or raw.get("Adapter") or "")
    return {
        "timestamp": str(raw.get("LogStart") or raw.get("LogEnd") or raw.get("timestamp") or ""),
        "error": str(err)[:4000],
        "message_id": str(raw.get("MessageGuid") or raw.get("message_id") or raw.get("MessageID") or ""),
        "adapter": adapter,
        "component": str(ia_id or raw.get("IntegrationFlowName") or raw.get("Component") or raw.get("IntegrationFlow") or ""),
        "package_id": pkg_id,
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
            "package_id": "",
        },
        {
            "timestamp": "2026-05-09T14:22:00.512Z",
            "error": "Target endpoint handshake failed — certificate chain validation error",
            "message_id": mid,
            "adapter": "HTTPS",
            "component": "ExternalCall",
            "package_id": "",
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
    Attempt real CPI OData query for MessageProcessingLogs (Swagger: MPL API).

    Filter order follows SAP note: ``IntegrationFlowName`` deprecated in favor of
    ``IntegrationArtifact/Id`` / ``IntegrationFlow/Id``.
    """
    url = base.rstrip("/") + _mpl_path()
    safe_flow = _odata_string(iflow_name)
    mid_suffix = f" and MessageGuid eq '{_odata_string(message_id)}'" if message_id else ""
    filter_attempts = [
        f"IntegrationArtifact/Id eq '{safe_flow}'{mid_suffix}",
        f"IntegrationFlow/Id eq '{safe_flow}'{mid_suffix}",
        f"IntegrationFlow eq '{safe_flow}'{mid_suffix}",
    ]

    try:
        last_status = 0
        last_snip = ""
        with httpx.Client(timeout=30.0) as client:
            for filt in filter_attempts:
                params: dict[str, str] = {"$format": "json", "$top": "25", "$filter": filt}
                r = client.get(url, params=params, auth=(user, password), headers={"Accept": "application/json"})
                last_status = r.status_code
                last_snip = r.text[:400]
                if r.status_code == 200:
                    payload = r.json()
                    rows = payload.get("d", {}).get("results") if isinstance(payload.get("d"), dict) else None
                    if rows is None and isinstance(payload.get("value"), list):
                        rows = payload["value"]
                    if rows is None:
                        rows = []
                    out: list[dict[str, str]] = []
                    for row in rows:
                        if isinstance(row, dict):
                            out.append(_normalize_log_entry(row))
                    return out
                if r.status_code not in (400, 404):
                    logger.warning("CPI OData logs HTTP %s: %s", r.status_code, r.text[:500])
                    return None
            logger.warning(
                "CPI OData logs: all filter variants failed (last HTTP %s): %s",
                last_status,
                last_snip,
            )
            return None
    except Exception as exc:  # noqa: BLE001 — degrade to mock on any integration issue
        logger.warning("CPI OData logs fetch failed: %s", exc)
        return None


def _try_fetch_failed_logs_odata(
    base: str,
    user: str,
    password: str,
    integration_artifact_id: str,
    *,
    lookback_minutes: int,
    top: int,
) -> list[dict[str, str]] | None:
    """
    MessageProcessingLogs filtered to FAILED rows for an integration artifact, newest first.

    Uses a rolling ``LogEnd`` window (OData ``datetime'…'`` UTC). Falls back to the same filters
    without the time clause if the tenant rejects the datetime predicate.
    """
    url = base.rstrip("/") + _mpl_path()
    safe_id = _odata_string(integration_artifact_id)
    since = datetime.now(timezone.utc) - timedelta(minutes=max(1, lookback_minutes))
    ts = since.strftime("%Y-%m-%dT%H:%M:%S")
    time_clause = f" and LogEnd ge datetime'{ts}'"
    filter_attempts = [
        f"Status eq 'FAILED' and IntegrationArtifact/Id eq '{safe_id}'{time_clause}",
        f"Status eq 'FAILED' and IntegrationFlow/Id eq '{safe_id}'{time_clause}",
        f"Status eq 'FAILED' and IntegrationArtifact/Id eq '{safe_id}'",
        f"Status eq 'FAILED' and IntegrationFlow/Id eq '{safe_id}'",
    ]
    try:
        last_status = 0
        last_snip = ""
        with httpx.Client(timeout=35.0) as client:
            for filt in filter_attempts:
                for use_order in (True, False):
                    params: dict[str, str] = {"$format": "json", "$top": str(max(1, top)), "$filter": filt}
                    if use_order:
                        params["$orderby"] = "LogEnd desc"
                    r = client.get(url, params=params, auth=(user, password), headers={"Accept": "application/json"})
                    last_status = r.status_code
                    last_snip = r.text[:400]
                    if r.status_code == 200:
                        payload = r.json()
                        rows = payload.get("d", {}).get("results") if isinstance(payload.get("d"), dict) else None
                        if rows is None and isinstance(payload.get("value"), list):
                            rows = payload["value"]
                        if rows is None:
                            rows = []
                        out: list[dict[str, str]] = []
                        for row in rows:
                            if isinstance(row, dict):
                                out.append(_normalize_log_entry(row))
                        return out
                    if r.status_code == 400 and use_order:
                        continue
                    break
                if last_status not in (400, 404):
                    logger.warning("CPI failed MPL HTTP %s: %s", last_status, last_snip[:300])
                    return None
        logger.warning("CPI failed MPL: all variants failed (last HTTP %s)", last_status)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("CPI failed MPL fetch: %s", exc)
        return None


def fetch_recent_failed_logs(
    integration_artifact_id: str,
    *,
    lookback_minutes: int = 15,
    top: int = 20,
) -> list[dict[str, str]]:
    """
    Recent **FAILED** Message Processing Log rows for one integration (iFlow artifact Id).

    Intended for the periodic monitor: combine with ``fetch_iflow_metadata`` + LLM briefing.
    Returns ``[]`` when mocked or when CPI is unreachable (no mock fallback — avoids false alerts).
    """
    if settings.cpi_use_mock:
        return []

    base = _normalize_tenant_base(settings.sap_cpi_base_url.strip())
    user = settings.sap_cpi_user
    password = settings.sap_cpi_password
    if not base or not user:
        return []

    fetched = _try_fetch_failed_logs_odata(
        base,
        user,
        password,
        integration_artifact_id,
        lookback_minutes=lookback_minutes,
        top=top,
    )
    return fetched if fetched is not None else []


def _designtime_prefix() -> str:
    """OData root for Integration Content entities (same ``api/v1`` root as MPL by default)."""
    custom = (settings.sap_cpi_designtime_odata_root or "").strip()
    if custom:
        p = custom.rstrip("/")
        return p if p.startswith("/") else f"/{p}"
    return _api_root()


def _odata_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize OData v2 `d.results` or OData v4 `value` to a list of objects."""
    if not isinstance(payload, dict):
        return []
    d = payload.get("d")
    if isinstance(d, dict) and isinstance(d.get("results"), list):
        return [x for x in d["results"] if isinstance(x, dict)]
    if isinstance(payload.get("value"), list):
        return [x for x in payload["value"] if isinstance(x, dict)]
    return []


def _unwrap_single_designtime_entity(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """Single IntegrationDesigntimeArtifacts entity from GET (wrapped ``d`` or bare object)."""
    if not detail or not isinstance(detail, dict):
        return None
    d = detail.get("d")
    if isinstance(d, dict) and not isinstance(d.get("results"), list):
        return d
    if "Id" in detail:
        return detail
    rows = _odata_rows(detail)
    return rows[0] if rows else None


def _cpi_get_json(
    base: str,
    path: str,
    user: str,
    password: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """GET JSON from CPI; returns None on non-200 or parse errors."""
    url = base.rstrip("/") + path
    q = {"$format": "json"}
    if params:
        q.update(params)
    try:
        with httpx.Client(timeout=45.0) as client:
            r = client.get(
                url,
                params=q,
                auth=(user, password),
                headers={"Accept": "application/json"},
            )
        if r.status_code != 200:
            logger.warning("CPI OData GET %s HTTP %s: %s", path, r.status_code, r.text[:400])
            return None
        return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("CPI OData GET %s failed: %s", path, exc)
        return None


def _designtime_entity_key(id_value: str, version: str) -> str:
    """OData key: IntegrationDesigntimeArtifacts(Id='..',Version='..') with quote escaping."""
    safe_id = _odata_string(id_value)
    safe_ver = _odata_string(version)
    return f"IntegrationDesigntimeArtifacts(Id='{safe_id}',Version='{safe_ver}')"


def _designtime_entity_nav(package_id: str | None, artifact_id: str, version: str) -> str:
    """
    Relative path under ``api/v1`` for an integration artifact.

    Some tenants (e.g. Integration Suite trial) require the package-scoped path from Swagger:
    ``IntegrationPackages('{PackageId}')/IntegrationDesigntimeArtifacts(Id=...,Version=...)``.
    """
    inner = _designtime_entity_key(artifact_id, version)
    if package_id:
        return f"IntegrationPackages('{_odata_string(package_id)}')/{inner}"
    return inner


def _version_sort_key(row: dict[str, Any]) -> tuple[int, ...]:
    v = str(row.get("Version") or "")
    parts: list[int] = []
    for p in v.replace("_", ".").split("."):
        if p.isdigit():
            parts.append(int(p))
        else:
            parts.append(0)
    return tuple(parts)


def _resolve_designtime_version_from_list(
    base: str,
    user: str,
    password: str,
    artifact_id: str,
) -> str | None:
    """Latest Version from root ``IntegrationDesigntimeArtifacts`` list, when tenant supports it."""
    root = _designtime_prefix()
    filt = f"Id eq '{_odata_string(artifact_id)}'"
    payload = _cpi_get_json(
        base,
        f"{root}/IntegrationDesigntimeArtifacts",
        user,
        password,
        params={"$filter": filt, "$top": "25"},
    )
    if not payload:
        return None
    rows = _odata_rows(payload)
    if not rows:
        return None
    rows.sort(key=_version_sort_key, reverse=True)
    v = rows[0].get("Version")
    return str(v) if v is not None else None


def _enumerate_designtime_in_packages(
    base: str,
    user: str,
    password: str,
    artifact_id: str,
) -> list[tuple[str, str, dict[str, Any]]]:
    """
    All ``(package_id, version, list_row)`` matches for ``artifact_id`` across integration packages.

    Same artifact Id can exist in multiple packages (e.g. SAP patterns vs your copy); callers
    should prefer ``IntegrationArtifact.PackageId`` from MPL when present.
    """
    root = _designtime_prefix()
    safe_art = _odata_string(artifact_id)
    found: dict[tuple[str, str], tuple[str, str, dict[str, Any]]] = {}
    skip = 0
    for _ in range(25):
        pkg_payload = _cpi_get_json(
            base,
            f"{root}/IntegrationPackages",
            user,
            password,
            params={"$format": "json", "$top": "50", "$skip": str(skip)},
        )
        if not pkg_payload:
            break
        packages = _odata_rows(pkg_payload)
        if not packages:
            break
        for pkg in packages:
            pid = pkg.get("Id")
            if not pid:
                continue
            safe_pkg = _odata_string(str(pid))
            nested_path = f"{root}/IntegrationPackages('{safe_pkg}')/IntegrationDesigntimeArtifacts"
            nested = _cpi_get_json(
                base,
                nested_path,
                user,
                password,
                params={"$filter": f"Id eq '{safe_art}'", "$top": "25", "$format": "json"},
            )
            rows = _odata_rows(nested or {})
            if not rows:
                nested2 = _cpi_get_json(
                    base,
                    nested_path,
                    user,
                    password,
                    params={"$top": "250", "$format": "json"},
                )
                rows = [r for r in _odata_rows(nested2 or {}) if str(r.get("Id")) == artifact_id]
            for row in rows:
                ver = row.get("Version")
                if ver is None:
                    continue
                key = (str(pid), str(ver))
                if key not in found or _version_sort_key(row) > _version_sort_key(found[key][2]):
                    found[key] = (str(pid), str(ver), row)
        if len(packages) < 50:
            break
        skip += 50
    out = list(found.values())
    out.sort(key=lambda t: _version_sort_key(t[2]), reverse=True)
    return out


def _is_likely_sap_template_package(package_id: str) -> bool:
    """SAP-shipped guideline / pattern packages often duplicate tutorial iFlow Ids."""
    p = package_id.lower()
    needles = (
        "designguideline",
        "guidelinespattern",
        "scriptingguideline",
        "managehistogram",
        "manageguideline",
    )
    return any(n in p for n in needles) or package_id.startswith("com.sap")


def _pick_designtime_location(
    base: str,
    user: str,
    password: str,
    artifact_id: str,
    *,
    preferred_package_id: str | None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """
    Choose a (package_id, version, list_row) that responds to ``Resources`` read.

    Tries ``preferred_package_id`` first (MPL ``IntegrationArtifact.PackageId`` when populated).
    Otherwise prefers **non-template** integration packages over SAP guideline copies.
    """
    root = _designtime_prefix()
    candidates = _enumerate_designtime_in_packages(base, user, password, artifact_id)
    if not candidates:
        return None, None, None

    pref = (preferred_package_id or "").strip()
    preferred = [c for c in candidates if pref and c[0] == pref]
    rest = [c for c in candidates if not pref or c[0] != pref]

    def sort_candidates(rows: list[tuple[str, str, dict[str, Any]]]) -> list[tuple[str, str, dict[str, Any]]]:
        return sorted(rows, key=lambda t: _version_sort_key(t[2]), reverse=True)

    userish = [c for c in rest if not _is_likely_sap_template_package(c[0])]
    template = [c for c in rest if _is_likely_sap_template_package(c[0])]
    ordered = sort_candidates(preferred) + sort_candidates(userish) + sort_candidates(template)

    for pkg, ver, list_row in ordered:
        nav = _designtime_entity_nav(pkg, artifact_id, ver)
        rp = _cpi_get_json(
            base,
            f"{root}/{nav}/Resources",
            user,
            password,
            params={"$top": "1", "$format": "json"},
        )
        if rp is not None:
            return pkg, ver, list_row
    # Fallback: best guess row for LLM even if Resources API rejects all paths
    pkg0, ver0, row0 = ordered[0]
    return pkg0, ver0, row0


def _resolve_designtime_version_via_packages(
    base: str,
    user: str,
    password: str,
    artifact_id: str,
) -> str | None:
    """Highest Version string for ``artifact_id`` under any integration package."""
    cands = _enumerate_designtime_in_packages(base, user, password, artifact_id)
    return cands[0][1] if cands else None


def _fetch_resources_count(
    base: str,
    user: str,
    password: str,
    entity_nav: str,
) -> int | None:
    """
    ``GET …/{entity_nav}/Resources/$count`` — ``entity_nav`` may be global or package-scoped
    (Swagger). Response is plain text integer.
    """
    root = _designtime_prefix()
    path = f"{root}/{entity_nav}/Resources/$count"
    url = base.rstrip("/") + path
    try:
        with httpx.Client(timeout=35.0) as client:
            r = client.get(url, auth=(user, password), headers={"Accept": "text/plain, */*"})
        if r.status_code != 200:
            logger.warning("Resources $count HTTP %s for %s", r.status_code, path)
            return None
        t = (r.text or "").strip()
        if t.isdigit():
            return int(t)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resources $count failed: %s", exc)
        return None


def _summarize_artifact(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep high-signal fields for LLM context (trim noise)."""
    keys = (
        "Id",
        "Version",
        "Name",
        "Namespace",
        "Description",
        "Type",
        "Vendor",
        "ArtifactContentReference",
        "CreatedBy",
        "CreatedAt",
        "ModifiedBy",
        "ModifiedAt",
        "ValidFrom",
        "ValidTo",
        "Status",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k not in raw:
            continue
        v = raw.get(k)
        if k in ("Id", "Version", "Name", "Namespace"):
            out[k] = v
        elif v not in (None, ""):
            out[k] = v
    return out


def _trim_configurations(rows: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        name = row.get("Name") or row.get("ParameterName") or row.get("Id")
        val = row.get("Value") or row.get("ParameterValue") or row.get("DefaultValue")
        if val is not None and isinstance(val, str) and len(val) > 500:
            val = val[:500] + "…"
        out.append({"Name": name, "Value": val, "raw_keys": list(row.keys())[:12]})
    return out


def _trim_resources(rows: list[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        out.append(
            {
                "Name": row.get("Name"),
                "ResourceType": row.get("ResourceType") or row.get("Type"),
                "Description": row.get("Description"),
            }
        )
    return out


def _derive_endpoints_adapters_security(
    artifact: dict[str, Any], resources: list[dict[str, Any]]
) -> tuple[list[str], list[str], str]:
    """Lightweight hints for the legacy metadata shape — LLM still gets full JSON."""
    endpoints: list[str] = []
    adapters: list[str] = []
    desc = str(artifact.get("Description") or "")
    ref = str(artifact.get("ArtifactContentReference") or "")
    if ref:
        endpoints.append(ref)
    for r in resources:
        rt = str(r.get("ResourceType") or "")
        nm = str(r.get("Name") or "")
        if rt or nm:
            adapters.append(f"{rt}:{nm}".strip(":"))
    sec = "Review Parameters / Configurations and receiver channels in artifact resources."
    if any("oauth" in str(r).lower() for r in adapters + [desc]):
        sec = "OAuth / security material referenced in configurations or resources — verify credentials."
    return endpoints[:30], adapters[:40], sec


def _fetch_message_mapping_hints(
    base: str,
    user: str,
    password: str,
    iflow_id: str,
    resource_names: list[str],
) -> list[dict[str, Any]]:
    """
    Correlate MessageMappingDesigntimeArtifacts when resource names look like mappings.

    CPI naming varies; we probe a small list filter on Id when possible.
    """
    root = _designtime_prefix()
    hints: list[dict[str, Any]] = []
    for name in resource_names[:8]:
        stem = name.rsplit(".", 1)[0] if "." in name else name
        if not stem:
            continue
        filt = f"Id eq '{_odata_string(stem)}'"
        payload = _cpi_get_json(
            base,
            f"{root}/MessageMappingDesigntimeArtifacts",
            user,
            password,
            params={"$filter": filt, "$top": "3"},
        )
        if not payload:
            continue
        for row in _odata_rows(payload):
            hints.append(
                {
                    "Id": row.get("Id"),
                    "Version": row.get("Version"),
                    "Name": row.get("Name"),
                    "Namespace": row.get("Namespace"),
                }
            )
    if hints:
        return hints
    # Broad fallback: small page, client-filter by iflow id substring (best-effort).
    payload = _cpi_get_json(
        base,
        f"{root}/MessageMappingDesigntimeArtifacts",
        user,
        password,
        params={"$top": "40"},
    )
    if not payload:
        return []
    needle = iflow_id.lower()
    out: list[dict[str, Any]] = []
    for row in _odata_rows(payload):
        blob = " ".join(str(row.get(k) or "") for k in ("Id", "Name", "Namespace", "Description")).lower()
        if needle in blob:
            out.append(
                {
                    "Id": row.get("Id"),
                    "Version": row.get("Version"),
                    "Name": row.get("Name"),
                    "Namespace": row.get("Namespace"),
                }
            )
        if len(out) >= 10:
            break
    return out


def _fetch_designtime_bundle(
    base: str,
    user: str,
    password: str,
    artifact_id: str,
    iflow_version: str | None,
    *,
    preferred_package_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Fetch IntegrationDesigntimeArtifacts + Configurations + Resources + ``Resources/$count``.

    Uses global entity URL when supported; otherwise **package-scoped** URLs per SAP Swagger
    (required on some Integration Suite trial tenants that return 501 for global reads).
    """
    root = _designtime_prefix()
    package_id: str | None = None
    version_candidates: list[str] = []
    if iflow_version and iflow_version.strip():
        version_candidates.append(iflow_version.strip())
    version_candidates.append("active")

    raw_artifact: dict[str, Any] | None = None
    version_used: str | None = None

    for ver in version_candidates:
        nav = _designtime_entity_nav(None, artifact_id, ver)
        detail = _cpi_get_json(base, f"{root}/{nav}", user, password)
        raw_artifact = _unwrap_single_designtime_entity(detail)
        if raw_artifact:
            version_used = ver
            package_id = None
            break

    if not raw_artifact:
        pkg_guess, ver_guess, list_row = _pick_designtime_location(
            base,
            user,
            password,
            artifact_id,
            preferred_package_id=preferred_package_id,
        )
        if ver_guess and list_row is not None:
            package_id = pkg_guess
            version_used = ver_guess
            nav = _designtime_entity_nav(package_id, artifact_id, version_used)
            detail = _cpi_get_json(base, f"{root}/{nav}", user, password)
            raw_artifact = _unwrap_single_designtime_entity(detail) or list_row
        else:
            resolved = _resolve_designtime_version_from_list(base, user, password, artifact_id)
            if not resolved:
                logger.warning("Could not resolve design-time Version for Id=%s", artifact_id)
                return None
            version_used = resolved
            nav = _designtime_entity_nav(None, artifact_id, version_used)
            detail = _cpi_get_json(base, f"{root}/{nav}", user, password)
            raw_artifact = _unwrap_single_designtime_entity(detail)
            if not raw_artifact:
                logger.warning("IntegrationDesigntimeArtifacts GET failed for Id=%s Version=%s", artifact_id, resolved)
                return None

    if not version_used:
        logger.warning("Missing Version after resolution for Id=%s", artifact_id)
        return None

    nav = _designtime_entity_nav(package_id, artifact_id, version_used)

    configs_payload = _cpi_get_json(base, f"{root}/{nav}/Configurations", user, password)
    resources_payload = _cpi_get_json(base, f"{root}/{nav}/Resources", user, password)

    configurations = _trim_configurations(_odata_rows(configs_payload or {}))
    resources_full = _odata_rows(resources_payload or {})
    resources = _trim_resources(resources_full)

    mapping_names = [str(r.get("Name") or "") for r in resources_full if r.get("Name")]
    mm = _fetch_message_mapping_hints(base, user, password, artifact_id, mapping_names)

    summary = _summarize_artifact(raw_artifact)
    endpoints, adapters, security = _derive_endpoints_adapters_security(raw_artifact, resources)
    mappings = [
        f"{m.get('Namespace') or ''}/{m.get('Name') or m.get('Id')} v{m.get('Version')}"
        for m in mm
        if m.get("Id") or m.get("Name")
    ]

    resources_count = _fetch_resources_count(base, user, password, nav)

    return {
        "source": "sap_odata_designtime",
        "iflow_name": artifact_id,
        "artifact_id": artifact_id,
        "integration_package_id": package_id,
        "artifact_version": version_used,
        "resources_count": resources_count,
        "designtime_artifact": summary,
        "configurations": configurations,
        "resources": resources,
        "message_mapping_artifacts": mm,
        "endpoints": endpoints,
        "adapters": adapters,
        "security": security,
        "mappings": mappings or [r.get("Name") for r in resources if r.get("ResourceType") == "mmap"],
    }


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

    base = _normalize_tenant_base(settings.sap_cpi_base_url.strip())
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
                "package_id": "",
            }
        ]
    return fetched


def fetch_iflow_metadata(
    iflow_name: str,
    iflow_version: str | None = None,
    integration_package_id: str | None = None,
) -> dict[str, Any]:
    """
    TOOL STEP 2 — Fetch iFlow design-time artifact details for LLM context.

    Uses CPI OData (same paths you use in Web / Postman):
      - IntegrationDesigntimeArtifacts(Id,Version)
      - .../Configurations
      - .../Resources
      - MessageMappingDesigntimeArtifacts (correlated by resource names / Id)

    When CPI_USE_MOCK=true or OData fails, returns the hackathon mock shape with
    source=mock_fallback so callers can tell real vs simulated data.
    """
    if settings.cpi_use_mock:
        m = _mock_iflow_metadata(iflow_name)
        m["source"] = "mock"
        return m

    base = _normalize_tenant_base(settings.sap_cpi_base_url.strip())
    user = settings.sap_cpi_user
    password = settings.sap_cpi_password
    if not base or not user:
        m = _mock_iflow_metadata(iflow_name)
        m["source"] = "mock_fallback"
        m["designtime_note"] = "Missing SAP_CPI_BASE_URL or SAP_CPI_USER — using mock metadata."
        return m

    bundle = _fetch_designtime_bundle(
        base,
        user,
        password,
        iflow_name.strip(),
        iflow_version,
        preferred_package_id=integration_package_id.strip() if integration_package_id else None,
    )
    if bundle:
        return bundle

    logger.warning("Design-time OData fetch failed for Id=%s — using mock metadata", iflow_name)
    m = _mock_iflow_metadata(iflow_name)
    m["source"] = "mock_fallback"
    m["designtime_note"] = (
        "OData IntegrationDesigntimeArtifacts (or navigations) did not return usable JSON. "
        "Check SAP_CPI_BASE_URL (tenant host), SAP_CPI_API_ROOT (default /api/v1), Id/Version, and user roles."
    )
    return m


def logs_and_metadata_snapshot(iflow_name: str, message_id: str | None, error_fallback: str | None) -> str:
    """Debug helper — JSON preview for logs/troubleshooting."""
    return json.dumps(
        {
            "logs": fetch_runtime_logs(iflow_name, message_id, error_fallback=error_fallback),
            "metadata": fetch_iflow_metadata(iflow_name),
        },
        indent=2,
    )
