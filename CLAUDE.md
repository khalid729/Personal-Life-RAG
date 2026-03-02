# Personal Life RAG

Arabic-first personal knowledge management: agentic RAG + knowledge graph + multi-modal.

## Architecture

```
FastAPI :8500 → Claude API (chat/tool-calling, when USE_CLAUDE_FOR_CHAT=true)
               → vLLM :8000 (extraction/enrichment/translation — always local)
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
├── middleware/auth.py    # Auth middleware + context vars for multi-tenancy
├── services/            # 10 async services (see services/CLAUDE.md)
├── routers/             # 17 REST routers (see routers/CLAUDE.md)
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
- **Dual LLM backend**: Claude API for chat/tool-calling (`chat_with_tools`, `stream_with_tool_detection`), vLLM/Qwen3-VL for everything else (extraction, enrichment, translation, vision/image analysis, PDF fallback). Controlled by `USE_CLAUDE_FOR_CHAT` flag with automatic vLLM fallback on Claude failure.
- **Multi-tenancy**: `contextvars` for per-user graph/collection/Redis prefix isolation. Middleware sets vars from `X-API-Key` header. `multi_tenant_enabled=False` by default (zero behavior change). UserRegistry loads from `data/users.json` seed file.
- **Chat flow**: POST /chat/v2 → LLM picks tools → code executes → LLM formats (2 LLM calls, 20 tools)
- **search_knowledge**: 3 parallel searches — `search_sections()` (section name + entity-in-section matches) → `search_nodes()` (global graph) → vector search; section results shown first for structured project content
- **search_reminders**: supports optional `query` param for fuzzy title search via `_find_matching_reminders()`, combined with `status` filter
- **Ingestion**: translate → chunk (1500 tokens) → parallel enrichment via `asyncio.gather` → embed + extract facts
- **File re-upload**: same hash = skip; same filename + different hash = replace old chunks + orphan entities + `SUPERSEDES` graph link; section assignments (`IN_SECTION`) are snapshotted before cleanup and restored on matching new entities via `get_file_section_map()` + `restore_section_links()`
- **Entity provenance**: `(Entity)-[:EXTRACTED_FROM]->(File)` — tracks which file an entity came from; orphans cleaned on re-upload
- **URL ingestion**: POST /ingest/url → GitHub parser (repo/blob/tree) + web fetch → ingest pipeline
- **Entity resolution**: vector similarity (0.85 person, 0.80 default) + graph CONTAINS fallback via `resolve_entity_name()`
- **Arabic names**: NER → `name_ar` on Person → `_display_name()` = `رهف (Rahaf)`
- **Auto-extraction**: conversational messages → safe types only (Person, Company, Knowledge, Location)
- **No confirmation flow**: tools execute directly, model reports actual success/failure
- **Auto-dismiss reminders**: task marked done → `_auto_dismiss_reminders()` fuzzy-matches pending reminders via `_find_matching_reminders()` and marks them done
- **Active project ingestion**: `session_id` from callers → router resolves `project_name` via `memory.get_active_project()` → threaded through files/retrieval/llm/graph → extract prompt suppresses rogue Projects + auto-links Task/Knowledge/Idea/Sprint via BELONGS_TO
- **Project sections**: `(Project)-[:HAS_SECTION]->(Section)` + `(Entity)-[:IN_SECTION]->(Section)` — topic or phase sections; `create_project_with_phases()` creates 4 default phases (Planning→Preparation→Execution→Review)
- **Lists**: standalone `List` + `ListEntry` nodes — `(List)-[:HAS_ENTRY]->(ListEntry)`, optional `(List)-[:BELONGS_TO]->(Project)`. Types: shopping, ideas, checklist, reference
- **manage_lists tool**: list/get/create/add_entry/check_entry/uncheck_entry/remove_entry/delete — bulk add via `entries` array
- **Prayer time reminders**: `prayer` param on create/update_reminder → `_get_prayer_time()` fetches from Aladhan API (cached daily), applies configurable offset (default 20min). Auto rolls to next day if prayer passed. Config: `prayer_city`, `prayer_country`, `prayer_method`, `prayer_offset_minutes`
- **Persistent reminders**: `persistent=true` on `create_reminder` → reminder auto-reschedules every `nag_interval_minutes` (default 30) after firing, until user marks done/cancels. Nag loop: fire → mark notified → `reschedule_persistent_reminder()` sets `due_date = now + interval`, clears `notified_at`
- **Snooze (fixed)**: `update_reminder(action=snooze)` keeps `status='pending'`, moves `due_date` to snooze target, clears `notified_at` so it re-fires. Resolves prayer time, date+time, or defaults to `nag_interval_minutes`. Works for all reminders (persistent resumes nagging after snooze)
- **Persistent + recurring combo**: persistent takes priority in `job_check_reminders` — nags every 30min until user says "done". On "done", `_handle_update_reminder` detects both flags → `advance_recurring_reminder` (keeps `status=pending`, advances to next occurrence) instead of marking done permanently
- **Telegram reply context**: `reply_to_message.text` prepended as `[رد على: "..."]` so LLM understands context (update vs create)
- **Location-based reminders**: `location_place` (named place) or `location_type` (POI type) on reminders. Webhook `POST /location/update` accepts HA/OwnTracks payloads → geofence check → Telegram notification. Places stored as graph nodes, zones tracked in Redis with cooldown.
- **manage_places tool**: CRUD for saved places (graph `Place` nodes). `_TOOL_ONLY_TYPES` prevents extraction creating rogue Places.

## Key Gotchas

- FalkorDB: primitives only; `r.key=$val` in SET only, not CREATE; `toLower()` for case-insensitive
- Qwen3: needs `enable_thinking: False` (handled in llm.py)
- `.env` overrides config.py defaults — check `.env` first
- Dual backend: only `chat_with_tools` + `stream_with_tool_detection` use Claude; all other LLM methods (`chat`, `extract_facts`, `classify_file`, `analyze_image`, `translate_*`) always use vLLM — requires server restart after changing `.env`
- Prompts MUST include current date/time (UTC+3)
- `datetime.utcnow()` deprecated → `datetime.now(timezone(timedelta(hours=3)))`
- Hijri dates: auto-convert year < 1900 via `hijri-converter`
- Extraction chunking uses hardcoded `max_tokens=3000` (retrieval.py:156) — needs larger context than ingestion chunks
- File re-upload replaces Qdrant chunks (tracked via `file_hash`) + cleans orphaned entities (via `EXTRACTED_FROM`); shared entities survive; `IN_SECTION` links are preserved via snapshot/restore
- `ensure_file_stub()` MUST run before `ingest_text()` — `_link_entity_to_file()` uses MATCH not MERGE, so File node must exist first
- Sections/Lists/Places: `_TOOL_ONLY_TYPES = {Section, ListEntry, Place}` — skipped during extraction, created via tools only
- Multi-tenancy: `_resolution_cache` keyed by `(graph_name, name, type)` to prevent cross-user entity resolution leaks
- Multi-tenancy: `asyncio.create_task` inherits context — `post_process()` background tasks correctly use the user's graph/collection
- Location: OwnTracks sends `_type` field — use `Field(alias="_type")` with `populate_by_name=True` in Pydantic model
- Location: cooldown (`location_cooldown_minutes=10`) prevents rapid-fire from GPS jitter at zone boundaries
- `delete_project()` cascades: deletes linked tasks, sections, lists, and list entries
- `merge_projects()` re-links sections (`HAS_SECTION`) and lists (`BELONGS_TO`) to target before deleting source
- OWUI internal messages (follow-ups, titles, chat history analysis) must be blocked by Pipe — `_INTERNAL_KEYWORDS` list; `#### Tools Available` block stripped by `_TOOLS_AVAILABLE_RE` in `_strip_owui_rag_context()`
- `post_process()` stores every conversation turn in Qdrant (`source_type=conversation`) — if OWUI garbage leaks through, it pollutes all future searches
- Snooze used to set `status='snoozed'` which dropped reminders from `due-reminders` query forever — now keeps `status='pending'`
- `due_date` + `time` must be merged at creation: LLM sends them as separate fields, but FalkorDB `due-reminders` query uses string comparison (`r.due_date <= $now`). Date-only `"2026-03-02"` is `<=` midnight ISO string, causing reminders to fire at midnight instead of their actual time. Fix: `_handle_create_reminder` merges `due_date + time` → `"2026-03-02T20:00"`
- Redis `hset` rejects `bool` values — `UserRegistry._store_profile()` converts `enabled` to `str`; `_load_from_redis()` parses back
