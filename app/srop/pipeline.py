import asyncio
import re
import time
import uuid
from dataclasses import dataclass

import structlog
from google.adk.runners import InMemoryRunner
from google.adk.sessions import InMemorySessionService
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.root_agent import root_agent
from app.db.models import AgentTrace, Message, Session
from app.errors import SessionNotFoundError, UpstreamTimeoutError
from app.settings import settings

logger = structlog.get_logger()

@dataclass
class TurnResult:
    reply: str
    routed_to: str
    trace_id: str


def check_guardrails(message: str) -> str | None:
    """
    Check if the user message is out of scope (e.g. creative writing, poems, jokes).
    Returns a refusal reply if it is, otherwise None.
    """
    message_lower = message.lower()
    out_of_scope_keywords = ["poem", "joke", "story", "write a song", "homework help", "creative writing", "write me a poem"]
    
    for kw in out_of_scope_keywords:
        if kw in message_lower:
            return "I am a Helix support concierge. I cannot assist with creative writing, jokes, or out-of-scope requests."
            
    return None


def redact_pii(text: str) -> str:
    """Regex-replace email addresses and phone numbers with [REDACTED]."""
    if not isinstance(text, str):
        return text
    # Basic email regex
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED]', text)
    # Basic phone regex (simplified)
    text = re.sub(r'\+?\d[\d\s\-\(\)]{7,}\d', '[REDACTED]', text)
    return text


def redact_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Apply PII redaction to tool call args and results."""
    redacted_calls = []
    for call in tool_calls:
        redacted_args = {}
        if "args" in call and call["args"]:
            for k, v in call["args"].items():
                if isinstance(v, str):
                    redacted_args[k] = redact_pii(v)
                else:
                    redacted_args[k] = v
                    
        redacted_result = call.get("result")
        if isinstance(redacted_result, str):
            redacted_result = redact_pii(redacted_result)
            
        redacted_calls.append({
            "tool_name": call.get("tool_name"),
            "args": redacted_args,
            "result": redacted_result
        })
    return redacted_calls


async def run_turn(session_id: str, user_message: str, db: AsyncSession) -> TurnResult:
    start_time = time.time()
    
    # Check guardrails
    refusal = check_guardrails(user_message)
    if refusal:
        # Write only the messages to the DB, no trace, no LLM cost
        user_msg = Message(session_id=session_id, role="user", content=user_message)
        assistant_msg = Message(session_id=session_id, role="assistant", content=refusal)
        db.add(user_msg)
        db.add(assistant_msg)
        
        # Load session to update turn count
        db_session = await db.get(Session, session_id)
        if db_session:
            db_session.state["turn_count"] = db_session.state.get("turn_count", 0) + 1
            await db.commit()
            
        return TurnResult(reply=refusal, routed_to="guardrails", trace_id="")

    # a. Fetch sessions row
    db_session = await db.get(Session, session_id)
    if not db_session:
        raise SessionNotFoundError(f"Session {session_id} not found")

    # b. Deserialize state
    state = db_session.state or {}
    user_id = db_session.user_id
    plan_tier = db_session.plan_tier
    turn_count = state.get("turn_count", 0)
    last_agent = state.get("last_agent", None)

    # c. Build ADK runner
    runner = InMemoryRunner(agent=root_agent)
    session_svc = InMemorySessionService()
    
    adk_session = await session_svc.create_session(app_name="helix_srop", user_id=user_id)
    adk_session.state.update({
        "user_id": user_id,
        "plan_tier": plan_tier,
        "turn_count": turn_count,
        "last_agent": last_agent
    })

    # d. Call runner.run_async inside asyncio.wait_for
    try:
        response = await asyncio.wait_for(
            runner.run_async(
                user_id=user_id,
                session_id=adk_session.id,
                new_message={"role": "user", "parts": [{"text": user_message}]}
            ),
            timeout=settings.LLM_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.error("upstream_timeout", session_id=session_id)
        raise UpstreamTimeoutError(f"LLM did not respond within {settings.LLM_TIMEOUT_SECONDS}s")

    # e. Collect ADK events
    final_reply = "No response"
    routed_to = "srop_root"
    tool_calls = []
    retrieved_chunk_ids = []
    
    async for event in response:
        if getattr(event, "type", None) == "tool_call":
            tool_calls.append({
                "tool_name": getattr(event, "tool_name", ""),
                "args": getattr(event, "tool_args", {}),
                "result": None, # Will fill if we get tool_result event
                "call_id": getattr(event, "id", "")
            })
            
        if getattr(event, "type", None) == "tool_result":
            call_id = getattr(event, "tool_call_id", getattr(event, "id", ""))
            for tc in tool_calls:
                # Naive matching if no IDs, or match by name if ADK lacks call IDs
                if tc["result"] is None and (tc.get("call_id") == call_id or tc["tool_name"] == getattr(event, "tool_name", "")):
                    tc["result"] = getattr(event, "result", getattr(event, "content", str(event)))
                    
                    if tc["tool_name"] == "search_docs" and isinstance(tc["result"], list):
                        # Extract chunk IDs
                        for chunk in tc["result"]:
                            if hasattr(chunk, "chunk_id"):
                                retrieved_chunk_ids.append(chunk.chunk_id)
                    break
        
        # In newer ADK versions or older ones, check methods
        if hasattr(event, "is_final_response") and event.is_final_response():
            if hasattr(event, "author") and event.author:
                routed_to = event.author
            
            if hasattr(event, "content") and hasattr(event.content, "parts") and len(event.content.parts) > 0:
                final_reply = event.content.parts[0].text

    # f. Write agent_traces row
    trace_id = str(uuid.uuid4())
    latency_ms = int((time.time() - start_time) * 1000)
    
    redacted_tool_calls = redact_tool_calls(tool_calls)

    trace = AgentTrace(
        trace_id=trace_id,
        session_id=session_id,
        routed_to=routed_to,
        tool_calls=redacted_tool_calls,
        retrieved_chunk_ids=retrieved_chunk_ids,
        latency_ms=latency_ms
    )
    db.add(trace)

    # g. Write messages rows
    user_msg = Message(session_id=session_id, role="user", content=user_message, trace_id=trace_id)
    assistant_msg = Message(session_id=session_id, role="assistant", content=final_reply, trace_id=trace_id)
    db.add(user_msg)
    db.add(assistant_msg)

    # h. Update session.state
    db_session.state["turn_count"] = turn_count + 1
    db_session.state["last_agent"] = routed_to
    
    # Preserve any changes made by tools (e.g. escalation_agent storing last_ticket_id)
    if "last_ticket_id" in adk_session.state:
        db_session.state["last_ticket_id"] = adk_session.state["last_ticket_id"]

    db_session.state = dict(db_session.state) # Force SQLAlchemy to see the change

    # i. Commit
    await db.commit()

    # j. Return TurnResult
    return TurnResult(reply=final_reply, routed_to=routed_to, trace_id=trace_id)
