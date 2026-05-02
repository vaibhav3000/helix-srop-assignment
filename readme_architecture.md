## Architecture

```text
                          +---------------------+
                          |    HTTP Client      |
                          +----------+----------+
                                     |
              POST /v1/sessions      |      POST /v1/chat/{id}      GET /v1/traces/{id}
                                     v
                +--------------------+--------------------+
                |           FastAPI Application           |
                |  /healthz   /v1/sessions                |
                |  /v1/chat/{session_id}                  |
                |  /v1/traces/{trace_id}                  |
                |  exception handlers (404, 504)          |
                +--------------------+--------------------+
                                     |
                                     v  Depends(get_db)
                     +---------------+--------------+
                     |        SROP Pipeline         |
                     |   app/srop/pipeline.py       |
                     |                              |
                     |  1. check_guardrails()       |
                     |  2. load state from DB JSON  |
                     |  3. build InMemoryRunner     |
                     |  4. inject state -> ADK      |
                     |  5. asyncio.wait_for(        |
                     |       runner.run_async())    |
                     |  6. parse ADK events         |
                     |  7. redact_tool_calls() PII  |
                     |  8. write trace + messages   |
                     |  9. update state JSON in DB  |
                     +-------+------+------+--------+
                             |      |      |
                             |      |      +---------------------------+
                             |      |                                  |
                             v      v                                  v
                    +--------+------+-------+            +------------+------+
                    |      srop_root        |            |   SQLite Database  |
                    |  (LlmAgent)           |            |                    |
                    |  gemini-2.0-flash     |            | sessions           |
                    |                       |            |  session_id (PK)   |
                    |  AgentTool routing    |            |  user_id           |
                    |  via function calling |            |  plan_tier         |
                    +--+--------+-------+--+            |  state (JSON)      |
                       |        |       |               |   turn_count       |
          +------------+   +----+   +---+---+           |   last_agent       |
          |                |        |       |           |   last_ticket_id   |
          v                v        v       v           |                    |
  +-------+------+  +------+------+ |  +---+----------+| messages           |
  |knowledge_agent|  |account_agent| |  |escalation_  ||  message_id (PK)   |
  |(LlmAgent)    |  |(LlmAgent)   | |  |agent (E2)   ||  session_id (FK)   |
  |              |  |             | |  |(LlmAgent)   ||  role, content     |
  | tool:        |  | tools:      | |  |             ||                    |
  | search_docs()|  | get_recent_ | |  | tool:       || agent_traces       |
  |              |  | builds()    | |  | create_     ||  trace_id (PK)     |
  | cites        |  | get_account_| |  | ticket()    ||  routed_to         |
  | [chunk_id]   |  | status()    | |  |             ||  tool_calls (JSON) |
  | in answer    |  | (mock data) | |  | writes to   ||  chunk_ids (JSON)  |
  +-------+------+  +-------------+ |  | tickets DB  ||  latency_ms        |
          |                         |  +-------------+|                    |
          v                         |                 | tickets (E2)       |
  +-------+------+                  |                 |  ticket_id (PK)    |
  |  ChromaDB    |                  |                 |  session_id (FK)   |
  |              |<-----------------+                 |  summary, priority |
  | collection:  |  (state JSON                       +--------------------+
  | "helix_docs" |   read/write)
  |              |
  | 768-dim      |
  | embeddings   |
  | stable IDs   |
  | sha256[:12]  |
  +--------------+
```

### Data Flow Summary

| Step | Component | What Happens |
|------|-----------|--------------|
| 1 | FastAPI route | Validates request body via Pydantic v2 |
| 2 | pipeline.run\_turn() | Loads session.state JSON from SQLite |
| 3 | check\_guardrails() | Refuses out-of-scope messages before any LLM call |
| 4 | InMemoryRunner | Injects DB state into ephemeral ADK session |
| 5 | srop\_root (LlmAgent) | Routes to sub-agent via AgentTool function calling |
| 6 | knowledge\_agent | Calls search\_docs(), cites chunk IDs in answer |
| 7 | account\_agent | Calls mock build/status tools |
| 8 | escalation\_agent | Calls create\_ticket(), stores ticket\_id in state |
| 9 | pipeline.run\_turn() | Parses events, redacts PII, writes trace + messages |
| 10 | pipeline.run\_turn() | Increments turn\_count, saves last\_agent to DB |
