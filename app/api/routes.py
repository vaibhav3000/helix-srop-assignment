from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import AgentTrace, Session
from app.db.session import get_db
from app.srop.pipeline import run_turn

router = APIRouter(prefix="/v1")


class CreateSessionRequest(BaseModel):
    user_id: str
    plan_tier: Literal["free", "pro", "enterprise"] = "free"


class CreateSessionResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    content: str


class ChatResponse(BaseModel):
    reply: str
    routed_to: str
    trace_id: str


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    db_session = Session(
        user_id=request.user_id,
        plan_tier=request.plan_tier,
        state={"turn_count": 0, "last_agent": None}
    )
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)

    return CreateSessionResponse(session_id=db_session.session_id)


@router.post("/chat/{session_id}", response_model=ChatResponse)
async def chat(session_id: str, request: ChatRequest, db: AsyncSession = Depends(get_db)):
    result = await run_turn(session_id=session_id, user_message=request.content, db=db)
    return ChatResponse(
        reply=result.reply,
        routed_to=result.routed_to,
        trace_id=result.trace_id
    )


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(AgentTrace).where(AgentTrace.trace_id == trace_id)
    result = await db.execute(stmt)
    trace = result.scalar_one_or_none()

    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    return {
        "trace_id": trace.trace_id,
        "session_id": trace.session_id,
        "routed_to": trace.routed_to,
        "tool_calls": trace.tool_calls,
        "retrieved_chunk_ids": trace.retrieved_chunk_ids,
        "latency_ms": trace.latency_ms,
        "created_at": trace.created_at.isoformat()
    }
