"""Shared API response shapes — CPI agent and health."""

from typing import Literal

from pydantic import BaseModel, Field

ErrorType = Literal["PKIX", "AUTH", "TIMEOUT", "MAPPING", "UNKNOWN"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class HealthResponse(BaseModel):
    """Simple liveness payload for demos and CI checks."""

    status: str
    app_name: str
    mock_alert_email: str = Field(
        default="integrationops-alerts@demo.example.com",
        description="Hackathon placeholder address shown in the UI as the mock notification target.",
    )


class AgentInvestigationRequest(BaseModel):
    """Input to the autonomous CPI investigation agent."""

    iflow_name: str = Field(..., min_length=1, description="SAP CPI iFlow / integration name")
    iflow_version: str | None = Field(
        None,
        description="Optional design-time Version (e.g. 1.0.5). If omitted, latest match from OData list is used.",
    )
    integration_package_id: str | None = Field(
        None,
        description="Optional integration package Id (MPL IntegrationArtifact.PackageId) to disambiguate artifact Id",
    )
    message_id: str | None = Field(None, description="Optional Message GUID from MPL")
    error_message: str | None = Field(
        None,
        description="Operator-reported or ticket error text — fallback when logs are sparse",
    )


class AgentEvidence(BaseModel):
    """Which tool outputs materially informed the analysis."""

    logs_used: bool
    metadata_used: bool


class IncidentRecord(BaseModel):
    """One persisted autonomous-monitor investigation (GET /incidents)."""

    id: int
    timestamp: str
    message_id: str
    iflow: str
    error_type: ErrorType
    severity: Severity
    root_cause: str
    recommendation: str
    confidence_score: int = Field(..., ge=0, le=100)
    jira_ticket_id: str | None = None
    investigation_status: str = Field(
        default="completed",
        description="completed | failed — monitor pipeline outcome",
    )


class IncidentsListResponse(BaseModel):
    """Payload for GET /incidents (newest incidents first inside ``incidents``)."""

    incidents: list[IncidentRecord]


class AgentInvestigationResponse(BaseModel):
    """Structured agent output — suitable for UI and ticketing integrations."""

    iflow: str
    error_summary: str
    error_type: ErrorType
    severity: Severity
    # 0 = no basis for the conclusion; 100 = strong alignment between briefing evidence and error_type/root_cause.
    confidence_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="How strongly runtime logs, metadata, and error clarity support the conclusion (integer 0-100)",
    )
    root_cause: str
    recommendation: str
    evidence: AgentEvidence
    agent_flow: list[str] = Field(
        ...,
        description="Ordered tool + reasoning steps executed by the agent",
    )
