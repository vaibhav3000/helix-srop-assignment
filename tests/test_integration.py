from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio

class FakeEvent:
    def __init__(self, is_final, author, text, event_type="text_response"):
        self.type = event_type
        self.author = author
        self._is_final = is_final

        class Parts:
            def __init__(self, text):
                self.text = text

        class Content:
            def __init__(self, text):
                self.parts = [Parts(text)]

        self.content = Content(text)

    def is_final_response(self):
        return self._is_final

async def fake_event_stream():
    async def _stream():
        yield FakeEvent(False, None, "Thinking...", event_type="thought")
        yield FakeEvent(True, "knowledge_agent", "You can rotate it via the settings page.")
    return _stream()

@patch("google.adk.runners.InMemoryRunner.run_async")
async def test_integration_flow(mock_run_async, client):
    mock_run_async.side_effect = lambda *args, **kwargs: fake_event_stream()

    # Create session
    resp1 = await client.post("/v1/sessions", json={"user_id": "test_user_1", "plan_tier": "free"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    session_id = data1["session_id"]

    # Turn 1
    resp2 = await client.post(f"/v1/chat/{session_id}", json={"content": "How do I rotate a deploy key?"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["routed_to"] == "knowledge_agent"
    assert "rotate it via the settings" in data2["reply"]
    trace_id_1 = data2["trace_id"]

    # Turn 2
    resp3 = await client.post(f"/v1/chat/{session_id}", json={"content": "Tell me more"})
    assert resp3.status_code == 200
    data3 = resp3.json()
    trace_id_2 = data3["trace_id"]

    assert trace_id_1 != trace_id_2

    # Verify trace from turn 2
    resp4 = await client.get(f"/v1/traces/{trace_id_2}")
    assert resp4.status_code == 200
    trace_data = resp4.json()
    assert trace_data["session_id"] == session_id
    assert trace_data["routed_to"] == "knowledge_agent"
