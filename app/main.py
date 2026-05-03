from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.db.models import Base
from app.db.session import async_engine
from app.errors import SessionNotFoundError, UpstreamTimeoutError
from app.obs.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # create tables on first boot (alembic handles prod migrations)
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await async_engine.dispose()


app = FastAPI(title="Helix SROP Backend", lifespan=lifespan)
app.include_router(api_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.exception_handler(SessionNotFoundError)
async def handle_session_not_found(request: Request, exc: SessionNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error_code": "SESSION_NOT_FOUND", "message": str(exc)},
    )


@app.exception_handler(UpstreamTimeoutError)
async def handle_upstream_timeout(request: Request, exc: UpstreamTimeoutError):
    return JSONResponse(
        status_code=504,
        content={"error_code": "UPSTREAM_TIMEOUT", "message": str(exc)},
    )
