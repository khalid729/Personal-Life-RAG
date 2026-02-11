# Personal Life RAG

Arabic-first personal knowledge management system with agentic RAG, knowledge graph, and multi-modal processing.

## Architecture

```
FastAPI :8500 → vLLM :8000 (Qwen2.5-VL-72B-Instruct W4A16, 32K ctx)
               → FalkorDB :6379 (knowledge graph)
               → Qdrant :6333 (BGE-M3, 1024-dim, GPU)
               → Redis :6380 (3-layer memory)
```

## Project Structure

```
app/
├── main.py              # Lifespan: start services → inject into app.state
├── config.py            # 50+ settings via pydantic BaseSettings
├── models/schemas.py    # 11 enums, 50+ Pydantic models
├── services/            # 8 async services (see services/CLAUDE.md)
├── routers/             # 15 REST routers (see routers/CLAUDE.md)
├── prompts/             # 7 prompt builders (see prompts/CLAUDE.md)
└── integrations/        # Telegram, Open WebUI, MCP (see integrations/CLAUDE.md)
```

## Commands

```bash
# Run API
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8500

# Quick import check
./venv/bin/python -c "from app.services.graph import GraphService; print('OK')"

# Test chat
curl -s -X POST http://localhost:8500/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "session_id": "dev"}'
```

## Core Patterns

- **All async**: httpx.AsyncClient, falkordb.asyncio, AsyncQdrantClient, redis.asyncio
- **Service lifecycle**: each service has `start()` / `stop()`, managed in `main.py` lifespan
- **Chat flow**: POST /chat → RetrievalService.retrieve_and_respond() → Think→Act→Reflect pipeline
- **Post-processing**: BackgroundTasks extracts facts from query + combined exchange, upserts to graph
- **Smart routing**: 20 keyword patterns → fast-path to graph strategy, fallback to LLM classify
- **Entity resolution**: vector-based dedup (0.85 person, 0.80 default) via `resolve_entity_name()`
- **Confirmation**: ONLY for delete/cancel intents; all other side-effects run directly

## Key Gotchas

- FalkorDB: primitive types only — convert dict→str, list[dict]→list[str]
- FalkorDB Cypher: `r.key = $val` only in SET, not in CREATE. Use `CREATE (r:Label {key: $val})`
- Pydantic: field names must not shadow type names (use `dt.date` not `date: date`)
- Qwen2.5-VL: model name set in config.py; `.env` can override — check `.env` first if mismatch
- System/extract prompts: MUST include current date/time (user's timezone UTC+3)
- `datetime.utcnow()` deprecated — use `datetime.now(timezone(timedelta(hours=3)))`
- Config tuning: `chunk_max_tokens=6000`, `chunk_overlap_tokens=300`, `max_context_tokens=40000`
- Hijri dates: `upsert_person()` auto-converts year < 1900 via `hijri-converter`
- Dep: `hijri-converter` for Hijri→Gregorian date conversion

## Phases (1–11 complete)

1. Core RAG  2. Agentic RAG + Files  3. Financial + Reminders  4. Smart Conversations
5. Interfaces (Telegram/WebUI/MCP)  6. Proactive System  7. Inventory  8. Entity Resolution
9. Advanced Inventory  10. Productivity  11. Infrastructure (backup/NER/streaming/graph-viz)
