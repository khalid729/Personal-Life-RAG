# Personal Life RAG

Arabic-first personal knowledge management: agentic RAG + knowledge graph + multi-modal.

## Architecture

```
FastAPI :8500 → vLLM :8000 (Qwen3-VL-32B-Instruct BF16, 72K ctx)
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
├── prompts/             # 7 prompt builders (see prompts/CLAUDE.md)
└── integrations/        # Telegram, Open WebUI, MCP (see integrations/CLAUDE.md)
```

## Commands

```bash
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8500          # Run API
./venv/bin/python -c "from app.services.graph import GraphService; print('OK')"  # Import check
curl -s -X POST http://localhost:8500/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "session_id": "dev"}'                     # Test chat
```

## Core Patterns

- **All async**: httpx, falkordb.asyncio, AsyncQdrantClient, redis.asyncio
- **Chat flow**: POST /chat → Think→Act→Reflect → response + BackgroundTasks extraction
- **Smart routing**: 20 keyword patterns → graph strategy, fallback LLM classify
- **Entity resolution**: vector dedup (0.85 person, 0.80 default) via `resolve_entity_name()`
- **Arabic names**: NER → `name_ar` on Person → `_display_name()` = `رهف (Rahaf)`
- **Confirmation**: ONLY for delete/cancel; all else runs directly

## Key Gotchas

- FalkorDB: primitives only; `r.key=$val` in SET only, not CREATE; `toLower()` for case-insensitive
- Qwen3: needs `enable_thinking: False` (handled in llm.py)
- `.env` overrides config.py defaults — check `.env` first
- Prompts MUST include current date/time (UTC+3)
- `datetime.utcnow()` deprecated → `datetime.now(timezone(timedelta(hours=3)))`
- Hijri dates: auto-convert year < 1900 via `hijri-converter`
