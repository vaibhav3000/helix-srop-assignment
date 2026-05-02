import asyncio
import sys
import os
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

from httpx import ASGITransport, AsyncClient
from app.main import app

# Golden Dataset: (Query, Expected Agent, Required Keyword)
GOLDEN_DATASET: List[Tuple[str, str, str]] = [
    ("How do I rotate a deploy key in Helix?", "knowledge_agent", "Settings"),
    ("What is my current build status?", "account_agent", "BUILD-"),
    ("Nothing is working, I want to talk to a human", "escalation_agent", "ticket"),
    ("Write me a poem about code", "guardrails", "Helix support concierge"),
    ("Who are you?", "srop_root", "Helix"),
    ("Can you check my build #99?", "account_agent", "SUCCESS"),
    ("I hate this service, escalate now!", "escalation_agent", "created"),
    ("What are the system requirements?", "knowledge_agent", "requirements"),
    ("How do I cancel my subscription?", "knowledge_agent", "billing"),
    ("Tell me a joke", "guardrails", "cannot assist"),
]

async def run_eval():
    print("Starting Helix SROP Eval Harness...")
    print("-" * 50)
    
    passed = 0
    total = len(GOLDEN_DATASET)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create a fresh session for the eval run
        sess_resp = await client.post("/v1/sessions", json={"user_id": "eval_user", "plan_tier": "pro"})
        session_id = sess_resp.json()["session_id"]
        
        for i, (query, exp_agent, exp_keyword) in enumerate(GOLDEN_DATASET):
            print(f"Test {i+1}/{total}: \"{query}\"")
            
            try:
                resp = await client.post(f"/v1/chat/{session_id}", json={"content": query})
                data = resp.json()
                
                actual_agent = data.get("routed_to", "unknown")
                reply = data.get("reply", "").lower()
                
                agent_match = actual_agent == exp_agent
                keyword_match = exp_keyword.lower() in reply
                
                if agent_match and keyword_match:
                    print(f"  PASSED (Agent: {actual_agent})")
                    passed += 1
                else:
                    print(f"  FAILED")
                    if not agent_match:
                        print(f"     Expected Agent: {exp_agent}, Got: {actual_agent}")
                    if not keyword_match:
                        print(f"     Expected Keyword: '{exp_keyword}' not found in reply")
            except Exception as e:
                print(f"  ERROR: {e}")
            
            print("-" * 30)
            # Avoid 429 rate limits on free tier
            if i < total - 1:
                await asyncio.sleep(35)

    score = (passed / total) * 100
    print(f"\nFINAL SCORE: {passed}/{total} ({score}%)")
    
    if score < 80:
        print("Warning: Accuracy below 80%")
        sys.exit(1)
    else:
        print("Accuracy check passed!")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(run_eval())
