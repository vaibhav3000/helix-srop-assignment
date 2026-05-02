import asyncio
import dataclasses
import re
import time
import uuid
from dataclasses import dataclass

import structlog
from google.adk.runners import InMemoryRunner
from google.adk.sessions import InMemorySessionService
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from google.genai.types import Content, Part

from app.agents.root_agent import root_agent
from app.db.models import AgentTrace, Message, Session
from app.errors import SessionNotFoundError, UpstreamTimeoutError
from app.settings import settings

logger = structlog.get_logger()


@dataclass
class TurnResult:
    """Represents the output of a single conversational turn.

    Attributes:
        reply: The final text response provided by the agent.
        routed_to: The name of the agent that generated the response.
        trace_id: A unique identifier for tracking this execution trace.
    """
    reply: str
    routed_to: str
    trace_id: str


# refuse off-topic requests early, before touching the LLM
def check_guardrails(message: str) -> str | None:
    """Checks the user message against a blocked keyword list to enforce guardrails.

    Args:
        message: The raw text input from the user.

    Returns:
        A refusal message string if a blocked keyword is found, otherwise None.
    """
    lowered = message.lower()
    blocked = ["poem", "joke", "story", "write a song", "homework help", "creative writing", "write me a poem"]
    # Check for simple substring matches to catch obvious out-of-scope requests
    for kw in blocked:
        if kw in lowered:
            return "I am a Helix support concierge. I cannot assist with creative writing, jokes, or out-of-scope requests."
    return None


def redact_pii(text: str) -> str:
    """Detects and redacts common Personally Identifiable Information (PII).

    Args:
        text: The string that may contain PII.

    Returns:
        The text with emails and phone numbers replaced by [REDACTED].
    """
    if not isinstance(text, str):
        return text
    # Redact email addresses
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED]', text)
    # Redact phone numbers (looks for 7+ consecutive digits, optional +, spaces, hyphens)
    text = re.sub(r'\+?\d[\d\s\-\(\)]{7,}\d', '[REDACTED]', text)
    return text


def redact_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Recursively redacts PII from tool call arguments and results.

    Args:
        tool_calls: A list of dictionaries representing tool executions.

    Returns:
        A list of sanitized tool call dictionaries suitable for storage.
    """
    out = []
    for call in tool_calls:
        clean_args = {}
        # Apply redaction to every string argument value
        for k, v in (call.get("args") or {}).items():
            clean_args[k] = redact_pii(v) if isinstance(v, str) else v

        result = call.get("result")
        # Apply redaction to string return values
        if isinstance(result, str):
            result = redact_pii(result)

        out.append({"tool_name": call.get("tool_name"), "args": clean_args, "result": result})
    return out


async def run_turn(session_id: str, user_message: str, db: AsyncSession) -> TurnResult:
    """Executes a single conversational turn, including guardrails, ADK execution, and state persistence.

    Args:
        session_id: The primary key of the session in the database.
        user_message: The latest input from the user.
        db: An active SQLAlchemy async session.

    Returns:
        A TurnResult object containing the reply, the responding agent, and the trace ID.
    """
    start_time = time.time()

    refusal = check_guardrails(user_message)
    if refusal:
        # log both sides, skip the trace
        db.add(Message(session_id=session_id, role="user", content=user_message))
        db.add(Message(session_id=session_id, role="assistant", content=refusal))

        db_session = await db.get(Session, session_id)
        if db_session:
            db_session.state["turn_count"] = db_session.state.get("turn_count", 0) + 1
            await db.commit()

        return TurnResult(reply=refusal, routed_to="guardrails", trace_id="")

    # load session
    db_session = await db.get(Session, session_id)
    if not db_session:
        raise SessionNotFoundError(f"Session {session_id} not found")

    state = db_session.state or {}
    user_id = db_session.user_id
    plan_tier = db_session.plan_tier
    turn_count = state.get("turn_count", 0)
    last_agent = state.get("last_agent", None)

    # build a fresh ADK runner for this turn; InMemoryRunner owns its session service
    runner = InMemoryRunner(agent=root_agent, app_name="helix_srop")
    session_svc = runner.session_service
    adk_session = await session_svc.create_session(app_name="helix_srop", user_id=user_id)
    adk_session.state.update({
        "user_id": user_id,
        "plan_tier": plan_tier,
        "turn_count": turn_count,
        "last_agent": last_agent,
    })

    # kick off the LLM
    response = runner.run_async(
        user_id=user_id,
        session_id=adk_session.id,
        new_message=Content(role="user", parts=[Part.from_text(text=user_message)]),
    )

    # walk the event stream
    final_reply = "No response"
    routed_to = "srop_root"
    tool_calls: list[dict] = []
    retrieved_chunk_ids: list[str] = []

    try:
        async with asyncio.timeout(settings.LLM_TIMEOUT_SECONDS):
            async for event in response:
                if getattr(event, "type", None) == "tool_call":
                    tool_calls.append({
                        "tool_name": getattr(event, "tool_name", ""),
                        "args": getattr(event, "tool_args", {}),
                        "result": None,
                        "call_id": getattr(event, "id", ""),
                    })

                if getattr(event, "type", None) == "tool_result":
                    call_id = getattr(event, "tool_call_id", getattr(event, "id", ""))
                    for tc in tool_calls:
                        # match by call_id, fall back to tool name
                        if tc["result"] is None and (tc.get("call_id") == call_id or tc["tool_name"] == getattr(event, "tool_name", "")):
                            raw = getattr(event, "result", getattr(event, "content", str(event)))
                            # Serialize dataclasses (like ChunkResult) to dictionaries so they can be JSON-encoded in SQLite
                            if isinstance(raw, list) and raw and dataclasses.is_dataclass(raw[0]):
                                tc["result"] = [dataclasses.asdict(x) for x in raw]
                            else:
                                tc["result"] = raw

                            # Extract chunk_ids specifically for tracking RAG retrieval effectiveness
                            if tc["tool_name"] == "search_docs" and isinstance(tc["result"], list):
                                for chunk in tc["result"]:
                                    if isinstance(chunk, dict) and "chunk_id" in chunk:
                                        retrieved_chunk_ids.append(chunk["chunk_id"])
                                    elif hasattr(chunk, "chunk_id"):
                                        retrieved_chunk_ids.append(chunk.chunk_id)
                            break

                if hasattr(event, "is_final_response") and event.is_final_response():
                    if getattr(event, "author", None):
                        routed_to = event.author
                    if hasattr(event, "content") and hasattr(event.content, "parts") and event.content.parts:
                        final_reply = event.content.parts[0].text
    except TimeoutError:
        logger.error("upstream_timeout", session_id=session_id)
        raise UpstreamTimeoutError(f"LLM did not respond within {settings.LLM_TIMEOUT_SECONDS}s")

    # write the trace
    trace_id = str(uuid.uuid4())
    latency_ms = int((time.time() - start_time) * 1000)

    db.add(AgentTrace(
        trace_id=trace_id,
        session_id=session_id,
        routed_to=routed_to,
        tool_calls=redact_tool_calls(tool_calls),
        retrieved_chunk_ids=retrieved_chunk_ids,
        latency_ms=latency_ms,
    ))
    db.add(Message(session_id=session_id, role="user", content=user_message))
    db.add(Message(session_id=session_id, role="assistant", content=final_reply))

    # persist state back to DB
    db_session.state["turn_count"] = turn_count + 1
    db_session.state["last_agent"] = routed_to
    # pick up any ticket_id the escalation tool may have written
    if "last_ticket_id" in adk_session.state:
        db_session.state["last_ticket_id"] = adk_session.state["last_ticket_id"]
    db_session.state = dict(db_session.state)

    await db.commit()

    return TurnResult(reply=final_reply, routed_to=routed_to, trace_id=trace_id)


async def run_turn_stream(session_id: str, user_message: str, db: AsyncSession) -> AsyncGenerator[str, None]:
    """Asynchronous generator that streams LLM tokens and handles state persistence at the end.
    
    Yields:
        SSE-formatted JSON strings containing 'token' or the final 'result'.
    """
    start_time = time.time()

    # Guardrails (Synchronous check, but we stream the refusal)
    refusal = check_guardrails(user_message)
    if refusal:
        db.add(Message(session_id=session_id, role="user", content=user_message))
        db.add(Message(session_id=session_id, role="assistant", content=refusal))
        db_session = await db.get(Session, session_id)
        if db_session:
            db_session.state["turn_count"] = db_session.state.get("turn_count", 0) + 1
            await db.commit()
        
        yield f"data: {{\"reply\": \"{refusal}\", \"routed_to\": \"guardrails\", \"trace_id\": \"\"}}\n\n"
        return

    # Load session
    db_session = await db.get(Session, session_id)
    if not db_session:
        raise SessionNotFoundError(f"Session {session_id} not found")

    state = db_session.state or {}
    user_id = db_session.user_id
    plan_tier = db_session.plan_tier
    turn_count = state.get("turn_count", 0)
    last_agent = state.get("last_agent", None)

    runner = InMemoryRunner(agent=root_agent, app_name="helix_srop")
    session_svc = runner.session_service
    adk_session = await session_svc.create_session(app_name="helix_srop", user_id=user_id)
    adk_session.state.update({
        "user_id": user_id,
        "plan_tier": plan_tier,
        "turn_count": turn_count,
        "last_agent": last_agent,
    })

    response = runner.run_async(
        user_id=user_id,
        session_id=adk_session.id,
        new_message=Content(role="user", parts=[Part.from_text(text=user_message)]),
    )

    full_reply = []
    routed_to = "srop_root"
    tool_calls: list[dict] = []
    retrieved_chunk_ids: list[str] = []

    try:
        async with asyncio.timeout(settings.LLM_TIMEOUT_SECONDS):
            async for event in response:
                # Track tool calls and results for the final trace
                if getattr(event, "type", None) == "tool_call":
                    tool_calls.append({
                        "tool_name": getattr(event, "tool_name", ""),
                        "args": getattr(event, "tool_args", {}),
                        "result": None,
                        "call_id": getattr(event, "id", ""),
                    })

                if getattr(event, "type", None) == "tool_result":
                    call_id = getattr(event, "tool_call_id", getattr(event, "id", ""))
                    for tc in tool_calls:
                        if tc["result"] is None and (tc.get("call_id") == call_id or tc["tool_name"] == getattr(event, "tool_name", "")):
                            raw = getattr(event, "result", getattr(event, "content", str(event)))
                            if isinstance(raw, list) and raw and dataclasses.is_dataclass(raw[0]):
                                tc["result"] = [dataclasses.asdict(x) for x in raw]
                            else:
                                tc["result"] = raw
                            
                            if tc["tool_name"] == "search_docs" and isinstance(tc["result"], list):
                                for chunk in tc["result"]:
                                    if isinstance(chunk, dict) and "chunk_id" in chunk:
                                        retrieved_chunk_ids.append(chunk["chunk_id"])
                            break

                # Stream parts/tokens as they arrive
                if hasattr(event, "content") and hasattr(event.content, "parts") and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            full_reply.append(part.text)
                            yield f"data: {{\"token\": {part.text!r}}}\n\n"

                if hasattr(event, "is_final_response") and event.is_final_response():
                    if getattr(event, "author", None):
                        routed_to = event.author

    except TimeoutError:
        logger.error("upstream_timeout", session_id=session_id)
        yield f"data: {{\"error\": \"LLM timeout\"}}\n\n"
        return

    # Finalize state and trace
    trace_id = str(uuid.uuid4())
    latency_ms = int((time.time() - start_time) * 1000)
    final_text = "".join(full_reply)

    db.add(AgentTrace(
        trace_id=trace_id,
        session_id=session_id,
        routed_to=routed_to,
        tool_calls=redact_tool_calls(tool_calls),
        retrieved_chunk_ids=retrieved_chunk_ids,
        latency_ms=latency_ms,
    ))
    db.add(Message(session_id=session_id, role="user", content=user_message))
    db.add(Message(session_id=session_id, role="assistant", content=final_text))

    db_session.state["turn_count"] = turn_count + 1
    db_session.state["last_agent"] = routed_to
    if "last_ticket_id" in adk_session.state:
        db_session.state["last_ticket_id"] = adk_session.state["last_ticket_id"]
    db_session.state = dict(db_session.state)

    await db.commit()

    yield f"data: {{\"reply\": {final_text!r}, \"routed_to\": \"{routed_to}\", \"trace_id\": \"{trace_id}\"}}\n\n"

