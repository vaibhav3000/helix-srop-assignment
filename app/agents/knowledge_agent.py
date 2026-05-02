from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from app.rag.retriever import search_docs
from app.settings import settings

knowledge_agent = LlmAgent(
    name="knowledge_agent",
    model=settings.MODEL_NAME,
    instruction=(
        "You are a Helix product support specialist. Answer only from the retrieved documentation. "
        "Every factual claim must cite the source chunk using [chunk_id] notation. "
        "If no relevant chunks are found, say so."
    ),
    tools=[FunctionTool(search_docs)]
)
