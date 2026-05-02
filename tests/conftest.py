"""
Test fixtures.

Key fixtures:
- `client`: async test client with in-memory SQLite DB
- `mock_adk`: patches the ADK root agent so tests don't hit the real LLM
- `seeded_db`: DB with a test user and session pre-created
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db):
    """Async test client with DB overridden to in-memory SQLite."""
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_adk(monkeypatch):
    class FakeEvent:
        def __init__(self, is_final, author, text, event_type="text_response", **kwargs):
            self.type = event_type
            self.author = author
            self._is_final = is_final
            for k, v in kwargs.items():
                setattr(self, k, v)
                
            class Parts:
                def __init__(self, text):
                    self.text = text
            class Content:
                def __init__(self, text):
                    self.parts = [Parts(text)]
            self.content = Content(text)
            
        def is_final_response(self):
            return self._is_final

    async def mock_run_async(self, user_id, session_id, new_message, *args, **kwargs):
        content = new_message.get("parts", [{}])[0].get("text", "")
        
        async def _stream():
            if "rotate" in content.lower():
                from dataclasses import dataclass
                @dataclass
                class DummyChunk:
                    chunk_id: str
                
                yield FakeEvent(False, None, "", event_type="tool_call", tool_name="search_docs", tool_args={"query": "deploy key"}, id="call_1")
                yield FakeEvent(False, None, "", event_type="tool_result", tool_call_id="call_1", tool_name="search_docs", result=[DummyChunk("test_chunk_1")])
                yield FakeEvent(True, "knowledge", "To rotate a deploy key...", event_type="text_response")
            else:
                yield FakeEvent(True, "account", "Your plan tier is pro.", event_type="text_response")
                
        return _stream()

    monkeypatch.setattr("google.adk.runners.InMemoryRunner.run_async", mock_run_async)
