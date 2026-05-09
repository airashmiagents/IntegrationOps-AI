"""Autonomous CPI incident investigation — exposes agents.agent.run_investigation."""

from fastapi import APIRouter

from agents.agent import run_investigation
from models.schemas import AgentInvestigationRequest, AgentInvestigationResponse

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/investigate", response_model=AgentInvestigationResponse)
def investigate(body: AgentInvestigationRequest) -> AgentInvestigationResponse:
    """
    Run the full agent pipeline: CPI tools → context merge → OpenRouter analysis.

    Works without real CPI credentials when CPI_USE_MOCK=true (default).
    """
    return run_investigation(
        iflow_name=body.iflow_name.strip(),
        message_id=body.message_id.strip() if body.message_id else None,
        error_message=body.error_message.strip() if body.error_message else None,
    )
