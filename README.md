# Helix SROP - Vaibhav Mahore

## Setup
```bash
git clone https://github.com/vaibhav3000/helix-srop-assignment.git
cd helix-srop-assignment
uv sync
cp .env.example .env  # fill in GOOGLE_API_KEY
uv run python -m app.rag.ingest --path docs/
uv run uvicorn app.main:app --reload
```

## Quick Test
```bash
SESSION=$(curl -s -X POST localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u_demo", "plan_tier": "pro"}' | jq -r .session_id)

curl -s -X POST localhost:8000/v1/chat/$SESSION \
  -H "Content-Type: application/json" \
  -d '{"content": "How do I rotate a deploy key?"}' | jq .
```

## Architecture
![System Architecture](docs/images/architecture.png)

## Design Decisions

### State persistence (Pattern 3)
I used Pattern 3 from the ADK guide (JSON column) because it avoids the overhead of pickling complete ADK objects and fully decouples the ephemeral ADK session memory from the primary storage, enabling horizontal scalability across multiple workers.

### Chunking strategy
I used heading-aware chunking because the Helix docs are heavily structured Markdown. Splitting at heading boundaries guarantees that each chunk contains a complete, logically cohesive section of documentation. 

### Vector store choice
I chose ChromaDB because it offers a frictionless, in-process, zero-setup experience for local development while providing robust vector search capabilities without requiring an external database cluster.

## Known Limitations
- **In-process ChromaDB**: Running Chroma locally in-process is great for development, but not suitable for high-concurrency production environments where multiple workers might attempt concurrent writes.
- **Mock Account Data**: The `account_agent` relies on hardcoded mock data for demonstration purposes rather than a live external API.
- **Trust-based Auth**: There is no real JWT or OAuth authentication; the system trusts the `user_id` provided in the request body.

## What I'd Do With More Time
- **Migrate to google.genai**: Transition the codebase from the deprecated `google.generativeai` SDK to the new `google.genai` library.
- **Implement Reranking**: Add an LLM-as-a-judge or cross-encoder reranking step to improve retrieval accuracy.
- **Productionize Vector DB**: Swap the local ChromaDB instance for a managed vector database like Pinecone.
- **Streaming Output**: Implement SSE streaming (`Accept: text/event-stream`) to lower perceived latency for the user.

## Time Spent
| Phase | Time |
|-------|------|
| Setup + DB + FastAPI boilerplate | 40 min |
| RAG ingest + search_docs | 50 min |
| ADK agents | 40 min |
| pipeline.py + state persistence | 60 min |
| Tests | 30 min |
| README | 20 min |
| **Total** | **~4 hours** |

## Extensions Completed
- [ ] E1: Idempotency
- [x] E2: Escalation agent
- [ ] E3: Streaming SSE
- [ ] E4: Reranking
- [x] E5: Guardrails
- [x] E6: Docker
- [ ] E7: Eval harness
