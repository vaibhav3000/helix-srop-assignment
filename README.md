# Helix SROP - Vaibhav Mahore

A production-quality multi-agent AI support backend built for the ServiceHive GenAI Engineer assignment. The system routes user queries across three specialist LLM agents, retrieves context from product documentation using RAG, persists conversation state across server restarts, and provides full observability through a trace API.

## Setup

```bash
git clone https://github.com/vaibhav3000/helix-srop-assignment.git
cd helix-srop-assignment
uv sync
cp .env.example .env  # fill in GOOGLE_API_KEY
uv run python -m app.rag.ingest --path docs/
uv run uvicorn app.main:app --reload
```

The server starts at `http://127.0.0.1:8000`. API docs are at `http://127.0.0.1:8000/docs`.

### Docker (Extension E6)

```bash
docker-compose up --build
```

Volumes are mounted for `helix.db` and `.chroma` so state and the vector index persist across container restarts.

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

### System Diagram

![System Architecture](docs/images/architecture.png)

### Detailed Component Diagram

```text
                         HTTP Client
                              |
         POST /v1/sessions    |    POST /v1/chat/{id}    GET /v1/traces/{id}
                              v
             +----------------+----------------+
             |         FastAPI Application      |
             |  app/main.py   app/api/routes.py |
             |  /healthz  exception handlers    |
             +---------+----------+------------+
                       |          |
          Depends(get_db)         | AsyncSession
                       v          v
            +----------+----------+----------+
            |       SROP Pipeline             |
            |   app/srop/pipeline.py          |
            |                                 |
            |  1. check_guardrails()          |
            |  2. load state from JSON col    |
            |  3. build InMemoryRunner        |
            |  4. inject state into ADK       |
            |  5. asyncio.wait_for(           |
            |       runner.run_async())       |
            |  6. parse ADK events            |
            |  7. redact_tool_calls() PII     |
            |  8. write trace + messages      |
            |  9. update state JSON in DB     |
            +---------+-------+------+--------+
                      |       |      |
                      v       v      v
            +---------+-------+------+--------+       +--------------------+
            |       srop_root (LlmAgent)       |       |   SQLite Database   |
            |       gemini-2.0-flash           |       |                    |
            |       AgentTool routing          |       | sessions           |
            +--+------------+------------+----+       |  session_id (PK)   |
               |            |            |            |  user_id           |
               v            v            v            |  plan_tier         |
        +------+----+ +-----+-----+ +----+--------+  |  state (JSON col)  |
        |knowledge_ | |account_   | |escalation_  |  |   turn_count       |
        |agent      | |agent      | |agent (E2)   |  |   last_agent       |
        |(LlmAgent) | |(LlmAgent) | |(LlmAgent)   |  |   last_ticket_id   |
        |           | |           | |             |  |                    |
        |tool:      | |tools:     | |tool:        |  | messages           |
        |search_docs| |get_recent_| |create_      |  |  role, content     |
        |           | |builds()   | |ticket()     |  |                    |
        |cites      | |get_account| |writes to    |  | agent_traces       |
        |[chunk_id] | |status()   | |tickets DB   |  |  routed_to         |
        +------+----+ |(mock data)| |returns id   |  |  tool_calls (JSON) |
               |      +-----------+ +-------------+  |  chunk_ids (JSON)  |
               v                                     |  latency_ms        |
        +------+----+                                |                    |
        | ChromaDB  |                                | tickets (E2)       |
        | helix_docs|                                |  ticket_id (PK)    |
        | 768-dim   |                                |  summary, priority |
        | vectors   |                                +--------------------+
        | sha256 IDs|
        +-----------+
```

### Request Lifecycle

| Step | Component | What Happens |
|------|-----------|--------------|
| 1 | FastAPI route | Validates request body via Pydantic v2 |
| 2 | pipeline.run_turn() | Loads session.state JSON from SQLite |
| 3 | check_guardrails() | Refuses out-of-scope messages before any LLM call |
| 4 | InMemoryRunner | Injects DB state into ephemeral ADK session |
| 5 | srop_root (LlmAgent) | Routes to sub-agent via AgentTool function calling |
| 6 | knowledge_agent | Calls search_docs(), cites chunk IDs in reply |
| 7 | account_agent | Calls mock build/status tools |
| 8 | escalation_agent | Calls create_ticket(), stores ticket_id in state |
| 9 | pipeline.run_turn() | Parses events, redacts PII, writes trace + messages |
| 10 | pipeline.run_turn() | Increments turn_count, saves last_agent to DB |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Google AI API key for Gemini and embeddings | required |
| `DATABASE_URL` | SQLAlchemy async database URL | `sqlite+aiosqlite:///./helix.db` |
| `CHROMA_PATH` | Path for ChromaDB persistent storage | `./.chroma` |
| `LLM_TIMEOUT_SECONDS` | Max seconds to wait for LLM response | `30` |
| `MODEL_NAME` | Gemini model name | `gemini-2.0-flash` |
| `EMBED_MODEL` | Embedding model name | `models/text-embedding-004` |

## API Reference

### POST /v1/sessions

```json
// Request
{"user_id": "demo_user", "plan_tier": "pro"}

// Response
{"session_id": "45c67b5f-9da5-43b7-b13c-5d142b7398cc"}
```

### POST /v1/chat/{session_id}

```json
// Request
{"content": "How do I rotate a deploy key in Helix?"}

// Response
{
  "reply": "To rotate a deploy key... [abc123def456]",
  "routed_to": "knowledge_agent",
  "trace_id": "5b10528e-2e78-4d7e-9357-18d3c3b00a14"
}
```

### GET /v1/traces/{trace_id}

```json
{
  "trace_id": "5b10528e-...",
  "session_id": "45c67b5f-...",
  "routed_to": "knowledge_agent",
  "tool_calls": [{"tool_name": "search_docs", "args": {}, "result": []}],
  "retrieved_chunk_ids": ["abc123def456", "789xyz012abc"],
  "latency_ms": 1243,
  "created_at": "2026-05-04T10:22:11"
}
```

### GET /healthz

Returns `{"status": "ok"}`.

### Error Responses

| HTTP Code | Error Code | Trigger |
|-----------|-----------|---------|
| 404 | `SESSION_NOT_FOUND` | session_id does not exist |
| 404 | `TRACE_NOT_FOUND` | trace_id does not exist |
| 504 | `UPSTREAM_TIMEOUT` | LLM exceeded timeout |
| 422 | Pydantic default | Request body fails validation |

## Design Decisions

### State Persistence (Pattern 3)

I used Pattern 3 from the ADK guide (JSON column) because it avoids the overhead of pickling complete ADK objects and fully decouples the ephemeral ADK session memory from the primary storage, enabling horizontal scalability across multiple workers. On every turn, `run_turn()` reads the state from the database, builds a transient `InMemoryRunner` with that state injected, runs the agent, then writes the updated state back. No in-process memory is relied upon.

### Chunking Strategy

I used heading-aware chunking because the Helix docs are heavily structured Markdown. Splitting at heading boundaries guarantees that each chunk contains a complete, logically cohesive section of documentation. Large sections exceeding 400 tokens are sub-split at sentence boundaries. Chunk IDs are generated as `sha256(filepath + "::" + chunk_index)[:12]`, making them stable across re-ingestion runs and preventing duplicates on subsequent ingest runs.

### AgentTool Routing (Not String Parsing)

The root agent routes to sub-agents using Google ADK's `AgentTool`, which exposes each sub-agent as a function call to the Gemini model. Routing is handled by the model's structured function-calling mechanism, not by parsing the model's text output. This is robust to rephrasing and cannot misroute due to string-matching failure.

### Vector Store Choice

I chose ChromaDB because it offers a frictionless, in-process, zero-setup experience for local development while providing robust vector search capabilities without requiring an external database cluster.

## Known Limitations

- **In-process ChromaDB**: Running Chroma locally in-process is great for development, but not suitable for high-concurrency production environments where multiple workers might attempt concurrent writes.
- **Mock Account Data**: The `account_agent` relies on hardcoded mock data for demonstration purposes rather than a live external API.
- **Trust-based Auth**: There is no real JWT or OAuth authentication; the system trusts the `user_id` provided in the request body.

## What I Would Do With More Time

- **Migrate to google.genai**: Transition the codebase from the deprecated `google.generativeai` SDK to the new `google.genai` library.
- **Implement Reranking**: Add an LLM-as-a-judge or cross-encoder reranking step to improve retrieval accuracy.
- **Productionize Vector DB**: Swap the local ChromaDB instance for a managed vector database like Pinecone.
- **Streaming Output**: Implement SSE streaming (`Accept: text/event-stream`) to lower perceived latency for the user.

## Running Tests

```bash
uv run pytest -q
```

Three test files are included:

- `tests/test_integration.py` - Multi-turn state persistence with mocked ADK runner
- `tests/test_rag.py` - `search_docs` with ephemeral ChromaDB and mocked embeddings
- `tests/test_guardrails.py` - Refusal logic and PII redaction

## Code Quality

```bash
uv run ruff check .
```

## Extensions Completed

- [x] E1: Idempotency
- [x] E2: Escalation agent
- [x] E3: Streaming SSE
- [x] E4: Reranking
- [x] E5: Guardrails
- [x] E6: Docker
- [x] E7: Eval harness

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