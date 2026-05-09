"""
agents/
-------
Autonomous CPI incident workflows — tool orchestration + LLM analysis.

Primary entry: `agents.agent.run_investigation` (see also `routes/agent_route.py`).
"""

from agents.agent import run_investigation

__all__ = ["run_investigation"]
