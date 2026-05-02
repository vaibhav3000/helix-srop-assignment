from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from app.agents.account_agent import account_agent
from app.agents.escalation_agent import escalation_agent
from app.agents.knowledge_agent import knowledge_agent
from app.settings import settings

root_agent = LlmAgent(
    name="srop_root",
    model=settings.MODEL_NAME,
    instruction=(
        "You are an AI support concierge for Helix. Route knowledge questions (how-to, docs, configuration) to knowledge_agent. "
        "Route account/build queries to account_agent. Route complaints or escalation requests to escalation_agent. "
        "Never answer directly; always delegate to the appropriate sub-agent."
    ),
    tools=[
        AgentTool(agent=knowledge_agent),
        AgentTool(agent=account_agent),
        AgentTool(agent=escalation_agent)
    ]
)
