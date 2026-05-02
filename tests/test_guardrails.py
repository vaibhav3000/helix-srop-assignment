import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.asyncio

async def test_guardrails_refusal():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session
        resp1 = await client.post("/v1/sessions", json={"user_id": "test_user_2", "plan_tier": "free"})
        assert resp1.status_code == 200
        session_id = resp1.json()["session_id"]
        
        # Turn with guardrail trigger
        resp2 = await client.post(f"/v1/chat/{session_id}", json={"content": "write me a poem about cats"})
        assert resp2.status_code == 200
        data = resp2.json()
        
        assert data["routed_to"] == "guardrails"
        assert "cannot assist with creative writing" in data["reply"]
        assert data["trace_id"] == ""
