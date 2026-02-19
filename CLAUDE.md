# Personal Life RAG

Arabic-first personal knowledge management: agentic RAG + knowledge graph + multi-modal.

## Architecture

```
FastAPI :8500 → vLLM :8000 (Qwen3-32B BF16, ~47K ctx)
               → FalkorDB :6379 (knowledge graph)
               → Qdrant :6333 (BGE-M3, 1024-dim)
               → Redis :6380 (3-layer memory)
```

## Structure

```
app/
├── main.py              # Lifespan: start services → inject app.state
├── config.py            # Settings via pydantic BaseSettings (.env overrides)
├── models/schemas.py    # Enums + Pydantic models
├── services/            # 8 async services (see services/CLAUDE.md)
├── routers/             # 15 REST routers (see routers/CLAUDE.md)
├── prompts/             # 6 prompt builders (see prompts/CLAUDE.md)
└── integrations/        # Telegram, Open WebUI, MCP (see integrations/CLAUDE.md)
```

## Commands

```bash
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8500          # Run API
./venv/bin/python -c "from app.services.graph import GraphService; print('OK')"  # Import check
curl -s -X POST http://localhost:8500/chat/v2 \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "session_id": "dev"}'                     # Test chat
```

## Core Patterns

- **All async**: httpx, falkordb.asyncio, AsyncQdrantClient, redis.asyncio
- **Chat flow**: POST /chat/v2 → LLM picks tools → code executes → LLM formats (2 LLM calls, 18 tools)
- **search_reminders**: supports optional `query` param for fuzzy title search via `_find_matching_reminders()`, combined with `status` filter
- **Ingestion**: translate → chunk (1500 tokens) → parallel enrichment via `asyncio.gather` → embed + extract facts
- **File re-upload**: same hash = skip; same filename + different hash = replace old chunks + orphan entities + `SUPERSEDES` graph link
- **Entity provenance**: `(Entity)-[:EXTRACTED_FROM]->(File)` — tracks which file an entity came from; orphans cleaned on re-upload
- **URL ingestion**: POST /ingest/url → GitHub parser (repo/blob/tree) + web fetch → ingest pipeline
- **Entity resolution**: vector similarity (0.85 person, 0.80 default) + graph CONTAINS fallback via `resolve_entity_name()`
- **Arabic names**: NER → `name_ar` on Person → `_display_name()` = `رهف (Rahaf)`
- **Auto-extraction**: conversational messages → safe types only (Person, Company, Knowledge, Location)
- **No confirmation flow**: tools execute directly, model reports actual success/failure
- **Auto-dismiss reminders**: task marked done → `_auto_dismiss_reminders()` fuzzy-matches pending reminders via `_find_matching_reminders()` and marks them done

## Key Gotchas

- FalkorDB: primitives only; `r.key=$val` in SET only, not CREATE; `toLower()` for case-insensitive
- Qwen3: needs `enable_thinking: False` (handled in llm.py)
- `.env` overrides config.py defaults — check `.env` first
- Prompts MUST include current date/time (UTC+3)
- `datetime.utcnow()` deprecated → `datetime.now(timezone(timedelta(hours=3)))`
- Hijri dates: auto-convert year < 1900 via `hijri-converter`
- Extraction chunking uses hardcoded `max_tokens=3000` (retrieval.py:156) — needs larger context than ingestion chunks
- File re-upload replaces Qdrant chunks (tracked via `file_hash`) + cleans orphaned entities (via `EXTRACTED_FROM`); shared entities survive
- `ensure_file_stub()` MUST run before `ingest_text()` — `_link_entity_to_file()` uses MATCH not MERGE, so File node must exist first
