# Helix SROP Assignment Implementation

This repository contains the completed technical assignment for the ServiceHive GenAI Engineer role. It implements a fully functional AI-powered support agent backend using FastAPI, google-adk, SQLAlchemy, and ChromaDB.

## Architecture

```text
+----------------+      +----------------+      +-------------------+
|                |      |                |      |                   |
|  User / Client +----->+ FastAPI Server +----->+ DB (SQLite/JSON)  |
|                |      |                |      | (Sessions/Traces) |
+----------------+      +-------+--------+      +-------------------+
                                |
                                v
                        +-------+--------+
                        |                |
                        |   SROP Root    |
                        |  (LlmAgent)    |
                        |                |
                        +---+----+---+---+
                            |    |   |
         +------------------+    |   +--------------------+
         |                       |                        |
         v                       v                        v
+--------+---------+   +---------+--------+    +----------+--------+
| Knowledge Agent  |   |  Account Agent   |    | Escalation Agent  |
|                  |   |                  |    |                   |
| + search_docs()  |   | + get_builds()   |    | + create_ticket() |
|                  |   | + get_status()   |    |                   |
+--------+---------+   +------------------+    +----------+--------+
         |
         v
+--------+---------+
|  Chroma DB       |
| (Vector Store)   |
+------------------+
```

## Setup & Running

1. Clone the repository and enter the directory:
   ```bash
   git clone https://github.com/vaibhav3000/helix-srop-assignment
   cd helix-srop
   ```
2. Install `uv` if not already installed:
   ```bash
   pip install uv
   ```
3. Install dependencies:
   ```bash
   uv sync
   ```
4. Copy the environment variables template and set your `GOOGLE_API_KEY`:
   ```bash
   cp .env.example .env
   # Edit .env and add your GOOGLE_API_KEY
   ```
5. Run the RAG ingestion pipeline:
   ```bash
   uv run python -m app.rag.ingest --path docs/
   ```
6. Start the API server:
   ```bash
   uv run uvicorn app.main:app --reload
   ```

Or using Docker (Extension E6):
```bash
docker-compose up --build
```

## Design Decisions

### State Persistence
I used Pattern 3 (JSON column on sessions table) because it requires no external service, survives process restarts, and keeps the state schema explicit and queryable.

### Document Chunking
Heading-aware chunking because the docs are structured Markdown; splitting at heading boundaries preserves logical sections and reduces context fragmentation. Large chunks are sub-split by sentence boundaries.

## Known Limitations
- Chroma runs in-process (not production-grade for concurrent writes).
- Mock account data is used for `account_agent` tools.
- No user authentication system (trusts `user_id` from request).
- Embedding happens synchronously in a loop for the ingest script (no batching/async mapping yet).

## Extensions Completed
- **E2: Escalation Agent**: A third sub-agent (`escalation_agent`) added to handle complaints and create support tickets via DB insertion.
- **E5: Guardrails**: Refusal checks and PII redaction for agent traces.
- **E6: Docker**: Added `Dockerfile` and `docker-compose.yml` for easy deployment.

## Time Breakdown

| Phase | Time Spent |
|-------|------------|
| Phase 0-2: Boilerplate & DB | 40 min |
| Phase 3-4: RAG Ingest & Retrieval | 50 min |
| Phase 5: ADK Agents Setup | 40 min |
| Phase 6-7: Core Pipeline & API | 60 min |
| Phase 8-9: Tests & Extensions | 50 min |
| Total | ~4 hours |
