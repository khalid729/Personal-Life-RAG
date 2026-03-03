# Personal Life RAG

Arabic-first personal knowledge management: agentic RAG + knowledge graph + multi-modal.

## Architecture

```
FastAPI :8500 → Claude API (chat/tool-calling + vision)
               → vLLM :8000 (extraction/enrichment/translation)
               → FalkorDB :6379 (knowledge graph)
               → Qdrant :6333 (BGE-M3, 1024-dim)
               → Redis :6380 (3-layer memory)
```

## Structure

```
app/
├── main.py              # Lifespan: start services → inject app.state
├── config.py            # Settings via pydantic BaseSettings (.env overrides)
├── models/schemas.py    # Enums + Pydantic models (UserProfile, UserContext)
├── middleware/auth.py    # Multi-tenancy: context vars from X-API-Key
├── services/            # 12 async services — see services/CLAUDE.md
├── routers/             # 18 REST routers — see routers/CLAUDE.md
├── prompts/             # 6 prompt builders — see prompts/CLAUDE.md
└── integrations/        # Telegram, Open WebUI, MCP — see integrations/CLAUDE.md
```

## Commands

```bash
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8500          # Run API
./venv/bin/python -c "from app.services.graph import GraphService; print('OK')"  # Import check
curl -s -X POST http://localhost:8500/chat/v2 \
  -H "Content-Type: application/json" -H "X-API-Key: <key>" \
  -d '{"message": "test", "session_id": "dev"}'                     # Test chat
sudo systemctl restart rag-server                                    # Restart API
sudo systemctl restart rag-telegram                                  # Restart Khalid bot
sudo systemctl restart rag-telegram-rawabi                           # Restart Rawabi bot
```

## Core Rules

These are the essential constraints — violating any of them causes bugs.

### Data Layer (FalkorDB)
- **Primitives only** in node properties — no dicts or nested objects
- **`r.key=$val`** works in SET only, NOT inside CREATE
- **`toLower()`** for case-insensitive filters
- **`GRAPH.CONSTRAINT CREATE`** not Cypher syntax
- **`collect()` inside `FOREACH` fails** — use two-step queries

### LLM Backend Split
- **Claude**: `chat_with_tools`, `stream_with_tool_detection`, `classify_file`, `analyze_image`
- **vLLM (always)**: `extract_facts`, `enrich_chunk`, `translate_*`, `chat` (format-reminders)
- **Fallback**: Claude → vLLM on failure. Streaming fallback only if no tokens yielded
- **Per-user Claude key**: `_get_anthropic_client()` reads `_current_anthropic_key` context var

### Prompts
- **MUST include current date/time (UTC+3)** in system + extract prompts
- `due_date` field name (not `date`) — extraction + reminders depend on this
- 6 examples max in extract prompt — more causes pollution
- **Gender-aware**: `build_tool_system_prompt(user_name=, is_female=)` — `_FEMALE_REPLACEMENTS` for female users

### Multi-Tenancy
- **6 context vars** in `auth.py`: `_current_graph_name`, `_current_collection`, `_current_redis_prefix`, `_current_user_nickname`, `_current_user_gender`, `_current_anthropic_key`
- `asyncio.create_task` inherits context — background tasks are correctly scoped
- `_resolution_cache` keyed by `(graph_name, name, type)` to prevent cross-user leaks
- Users: Khalid (أبو إبراهيم, `personal_life`) + Rawabi (أم سليمان, `personal_life_rawabi`)
- Seed file: `data/users.json` (contains API keys + bot tokens — gitignored)
- **Cross-user messaging** (Phase 25): `send_to_user` tool + `target_user` on `create_reminder`; per-user `telegram_bot_token` on UserProfile/UserContext

### Ingestion
- **`ensure_file_stub()` MUST run before `ingest_text()`** — MATCH not MERGE
- `_TOOL_ONLY_TYPES = {Section, ListEntry, Place}` — skipped in extraction
- Re-upload: same hash=skip, same name+diff hash=replace chunks+orphans+SUPERSEDES link
- `embed_only=True` skips enrichment/extraction (used after Claude Vision analysis)

### Reminders
- **`due_date + time` must be merged**: LLM sends separate fields, FalkorDB uses string comparison → date-only fires at midnight. Fix: `_handle_create_reminder` merges → `"2026-03-02T20:00"`
- Snooze keeps `status='pending'` (old `'snoozed'` status was a bug — dropped from query)
- Persistent + recurring: persistent priority in `job_check_reminders`, on "done" → `advance_recurring_reminder`

### Config
- `.env` overrides `config.py` — always check `.env` first
- `datetime.utcnow()` deprecated → `datetime.now(timezone(timedelta(hours=3)))`
- Qwen3: needs `enable_thinking: False` (handled in `llm.py`)
- Server restart required after `.env` changes

## Problem → Where to Look

| Problem | Files to check |
|---------|---------------|
| Chat not responding | `tool_calling.py`, `llm.py`, `auth.py` |
| Wrong user data / cross-leak | `auth.py` (context vars), `graph.py` (`_get_graph`) |
| Reminder timing wrong | `tool_calling.py` (`_handle_create_reminder`), `proactive.py` |
| Search returns nothing | `graph.py` (`search_nodes`), `vector.py`, `tool_calling.py` |
| File upload fails | `files.py`, `retrieval.py`, `graph.py` (`ensure_file_stub`) |
| Telegram bot silent | `telegram_bot.py` (`authorized`, `_load_tg_users`) |
| Open WebUI garbage | `openwebui_pipe.py` (`_strip_owui_rag_context`) |
| Claude API error | `llm.py` (`_get_anthropic_client`, `_convert_messages_to_anthropic`) |
| Entity not resolved | `graph.py` (`resolve_entity_name`, `_resolve_by_graph_contains`) |
| Project/section issues | `graph.py` (section CRUD), `tool_calling.py` (`manage_projects`) |
| Location reminder | `location.py`, `proactive.py`, router `location.py` |
| Expense cascade | `tool_calling.py` (`_cascade_expense_update`), `graph.py` |
| Cross-user msg not sent | `tool_calling.py` (`_handle_send_to_user`, `_resolve_target_user`) |
| Cross-user reminder wrong graph | `tool_calling.py` (`_handle_create_reminder`, target_user) |
| HA device not found | `homeassistant.py` (`resolve_entity`), `tool_calling.py` (`_handle_control_device`) |
| HA action not executing | `homeassistant.py` (`call_service`), `telegram_bot.py` (`job_check_reminders` HA block) |
| HA webhook not notifying | `routers/homeassistant.py` (`ha_webhook`), Telegram bot token |
