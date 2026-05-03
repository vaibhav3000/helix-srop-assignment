from google.adk.models.lite_llm import LiteLlm
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from app.agents.account_agent import account_agent
from app.agents.escalation_agent import escalation_agent
from app.agents.knowledge_agent import knowledge_agent
from app.settings import settings

# Define the primary entry-point agent that orchestrates the conversational flow.
# This agent does not handle requests directly; it delegates them to specialized sub-agents.
root_agent = LlmAgent(
    name="srop_root",
    model=LiteLlm(model=settings.GROQ_MODEL_NAME),
    instruction=(
        "You are an AI support concierge for Helix. "
        "For knowledge questions (how-to, docs, configuration), call the 'transfer_to_knowledge_agent' tool. "
        "For account/build queries, call the 'transfer_to_account_agent' tool. "
        "For complaints or escalation requests, call the 'transfer_to_escalation_agent' tool. "
        "Never answer directly; always delegate to the appropriate sub-agent tool."
    ),
    tools=[
        AgentTool(agent=knowledge_agent),
        AgentTool(agent=account_agent),
        AgentTool(agent=escalation_agent)
    ]
)
