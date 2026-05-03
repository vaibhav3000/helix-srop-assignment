from typing import Literal

from google.adk.models.lite_llm import LiteLlm
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from app.db.models import Ticket
from app.db.session import AsyncSessionLocal
from app.settings import settings


async def create_ticket(user_id: str, summary: str, priority: Literal["low", "medium", "high"]) -> dict:
    """Creates an escalation ticket for the user and returns the ticket_id."""
    async with AsyncSessionLocal() as session:
        ticket = Ticket(user_id=user_id, summary=summary, priority=priority)
        session.add(ticket)
        await session.commit()
        return {"ticket_id": ticket.ticket_id}


escalation_agent = LlmAgent(
    name="escalation_agent",
    model=LiteLlm(model=settings.GROQ_MODEL_NAME),
    instruction="You are an escalation specialist. Create support tickets for user complaints or escalation requests.",
    tools=[FunctionTool(create_ticket)]
)
