from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from app.settings import settings


def get_recent_builds(user_id: str, limit: int = 5) -> list[dict]:
    """Returns mock list of recent builds for the user."""
    return [
        {"status": "success", "timestamp": "2026-05-01T10:00:00Z", "error_message": None},
        {"status": "failed", "timestamp": "2026-05-02T09:30:00Z", "error_message": "OOM Error"},
    ][:limit]


def get_account_status(user_id: str) -> dict:
    """Returns mock account status including plan, remaining builds, and health."""
    return {
        "plan_tier": "pro",
        "builds_remaining": 42,
        "account_health": "good"
    }


account_agent = LlmAgent(
    name="account_agent",
    model=settings.MODEL_NAME,
    instructions="You are an account and build specialist. Answer questions based on the user's account and build status.",
    tools=[FunctionTool(get_recent_builds), FunctionTool(get_account_status)]
)
