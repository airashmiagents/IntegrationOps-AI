"""Shared API response shapes — CPI agent and health."""

from typing import Literal

from pydantic import BaseModel, Field

ErrorType = Literal["PKIX", "AUTH", "TIMEOUT", "MAPPING", "UNKNOWN"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class HealthResponse(BaseModel):
    """Simple liveness payload for demos and CI checks."""

    status: str
    app_name: str


class AgentInvestigationRequest(BaseModel):
    """Input to the autonomous CPI investigation agent."""

    iflow_name: str = Field(..., min_length=1, description="SAP CPI iFlow / integration name")
    message_id: str | None = Field(None, description="Optional Message GUID from MPL")
    error_message: str | None = Field(
        None,
        description="Operator-reported or ticket error text — fallback when logs are sparse",
    )


class AgentEvidence(BaseModel):
    """Which tool outputs materially informed the analysis."""

    logs_used: bool
    metadata_used: bool


class AgentInvestigationResponse(BaseModel):
    """Structured agent output — suitable for UI and ticketing integrations."""

    iflow: str
    error_summary: str
    error_type: ErrorType
    severity: Severity
    root_cause: str
    recommendation: str
    evidence: AgentEvidence
    agent_flow: list[str] = Field(
        ...,
        description="Ordered tool + reasoning steps executed by the agent",
    )
