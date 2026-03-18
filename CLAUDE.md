# Personal Life RAG

Arabic-first personal knowledge management: agentic RAG + knowledge graph + multi-modal.

## Architecture

```
FastAPI :8500 → Claude API (chat/tool-calling + vision)
               → vLLM :8000 Qwen3.5-35B-A3B MoE (extraction/enrichment/translation)
               → Deepgram API (Nova-3 Arabic STT, ar-SA dialect)
               → FalkorDB :6379 (knowledge graph)
               → Qdrant :6333 (BGE-M3, 1024-dim)
               → Redis :6380 (3-layer memory)
STT Proxy :8200 → Deepgram Nova-3 (OpenAI-compatible, for OWUI)
OWUI :3000      → ElevenLabs TTS (eleven_multilingual_v2) + STT Proxy
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
├── integrations/        # Telegram, Open WebUI, MCP — see integrations/CLAUDE.md
scripts/
└── deepgram_stt_proxy.py  # OpenAI-compatible STT proxy → Deepgram Nova-3 (:8200)
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
sudo systemctl restart rag-stt-proxy                                 # Restart Deepgram STT proxy
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
- **`USE_CLAUDE_FOR_EXTRACTION=true`** (experimental): routes `extract_facts`, `enrich_chunk`, `translate_*`, `summarize_*` to Claude instead of vLLM. Fallback to vLLM on failure
- **vLLM model**: Qwen3.5-35B-A3B (MoE, 3B active params, vision built-in) — `--enforce-eager` required (CUDA graph bug with Gated DeltaNet)
- **Fallback**: Claude → vLLM on failure. Streaming fallback only if no tokens yielded
- **Per-user Claude key**: `_get_anthropic_client()` reads `_current_anthropic_key` context var
- **Per-user Claude model**: `_get_anthropic_model()` reads `_current_anthropic_model` context var (e.g., Khalid→Haiku, Rawabi→Sonnet)
- **Revert to vLLM-only processing**: set `USE_CLAUDE_FOR_EXTRACTION=false` in `.env` + restart server. `chat_stream` (format-reminders) always uses vLLM regardless of this flag

### Prompts
- **MUST include current date/time (UTC+3)** in system + extract prompts
- `due_date` field name (not `date`) — extraction + reminders depend on this
- 6 examples max in extract prompt — more causes pollution
- **Gender-aware**: `build_tool_system_prompt(user_name=, is_female=)` — `_FEMALE_REPLACEMENTS` for female users

### Multi-Tenancy
- **7 context vars** in `auth.py`: `_current_graph_name`, `_current_collection`, `_current_redis_prefix`, `_current_user_nickname`, `_current_user_gender`, `_current_anthropic_key`, `_current_anthropic_model`
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
- **`create_reminder` clears `notified_at`**: when reusing an existing pending reminder, `notified_at=NULL` ensures it fires again
- **HA automations are NOT reminders**: `is_ha_automation=true` flag on Reminder nodes with `ha_entity_id`+`ha_action` — excluded from all reminder queries, daily plan, summaries, search

### Home Assistant (Phase 26)
- **Entity resolution**: always resolve via `ha.resolve_entity()` — LLM may hallucinate entity_ids like `light.left`
- **Arabic normalization**: `_normalize_ar()` treats ة=ه, أ/إ/آ=ا, ى=ي — fixes "غرفة نومي" matching "غرفه نومي"
- **Domain-aware matching**: query keywords (لمبة→light/switch, مكيف→climate) prevent wrong domain matches
- **`ha_entity_id` must be Arabic name**: tool description + prompt instruct LLM to send Arabic device name, not English entity_id
- **HA automations separate from reminders**: `is_ha_automation=true` on Reminder node → filtered from `query_reminders`, `query_daily_plan`, `due-reminders`, `noon-checkin`, `evening-summary`, `search_reminders`
- **Streaming fix**: tool calls take priority over streamed text — Haiku emits both simultaneously, tools must execute first

### OWUI Voice Call Mode (Phase 27)
- **STT**: Deepgram Nova-3 via `rag-stt-proxy` (:8200) — OpenAI-compatible proxy (`scripts/deepgram_stt_proxy.py`)
- **TTS**: ElevenLabs `eleven_multilingual_v2` — Docker env vars on OWUI container
- **Voice detection**: `_is_voice_mode()` reads `__metadata__.features.voice` (NOT `body.features`) — OWUI passes features in metadata for Pipes
- **Concise prefix**: when voice detected, injects `_VOICE_PREFIX` to keep responses short (1-2 sentences, no emoji/formatting)
- **`voice_concise` Valve**: controls concise injection (default True)
- **STT proxy gotchas**: do NOT set `encoding`/`sample_rate` params (Deepgram auto-detects from headers); do NOT convert audio via ffmpeg (degrades accuracy)
- **ElevenLabs API key**: must be unrestricted — restricted keys return 401 even with valid credits
- **Billing**: per-character (starter: 90K chars/month)

### OpenClaw Integration (Phase 28)
- **Webhook**: `POST /integrations/openclaw/report` — receives structured reports from NemoClaw (water monitoring, etc.)
- **Storage**: Knowledge node with `category=openclaw-{source}`, `source=openclaw`, `report_time` + vector embedding (`embed_only=True`)
- **Critical alerts**: only `severity=critical` sends immediate Telegram notification; `info`/`warning` are silent
- **Morning summary**: `job_morning_summary()` fetches `/proactive/latest-water-report` and appends to daily message (Khalid only — report stored in `personal_life` graph)
- **Water report query**: `GET /proactive/latest-water-report` — returns latest `openclaw-homeassistant` Knowledge node
- **Chart support**: `metadata.chart_base64` → sent as Telegram photo on critical alerts

### Config
- `.env` overrides `config.py` — always check `.env` first
- `datetime.utcnow()` deprecated → `datetime.now(timezone(timedelta(hours=3)))`
- Qwen3/3.5: needs `enable_thinking: False` (handled in `llm.py` — `"Qwen3" in model` matches both)
- Server restart required after `.env` changes

## Problem → Where to Look

| Problem | Files to check |
|---------|---------------|
| Chat not responding | `tool_calling.py`, `llm.py`, `auth.py` |
| Wrong user data / cross-leak | `auth.py` (context vars), `graph.py` (`_get_graph`) |
| Reminder timing wrong | `tool_calling.py` (`_handle_create_reminder`), `proactive.py` |
| Search returns nothing | `graph.py` (`search_nodes`), `vector.py`, `tool_calling.py` |
| File upload fails | `files.py`, `retrieval.py`, `graph.py` (`ensure_file_stub`) |
| Voice transcription fails | `files.py` (`_transcribe_deepgram`), check `DEEPGRAM_API_KEY` in `.env` |
| Telegram bot silent | `telegram_bot.py` (`authorized`, `_load_tg_users`) |
| Open WebUI garbage | `openwebui_pipe.py` (`_strip_owui_rag_context`) |
| Claude API error | `llm.py` (`_get_anthropic_client`, `_convert_messages_to_anthropic`) |
| Entity not resolved | `graph.py` (`resolve_entity_name`, `_resolve_by_graph_contains`) |
| Project/section issues | `graph.py` (section CRUD), `tool_calling.py` (`manage_projects`) |
| Location reminder | `location.py`, `proactive.py`, router `location.py` |
| Expense cascade | `tool_calling.py` (`_cascade_expense_update`), `graph.py` |
| Cross-user msg not sent | `tool_calling.py` (`_handle_send_to_user`, `_resolve_target_user`) |
| Cross-user reminder wrong graph | `tool_calling.py` (`_handle_create_reminder`, target_user) |
| Proactive msg wrong gender/name | `proactive.py` (`format_reminders` `user_name` + `is_female`), `telegram_bot.py` (`nickname` + `gender` in cache) |
| HA device not found | `homeassistant.py` (`resolve_entity`), `tool_calling.py` (`_handle_control_device`) |
| HA action not executing | `homeassistant.py` (`call_service`), `telegram_bot.py` (`job_check_ha_reminders`), `proactive.py` (`due-ha-automations`), `graph.py` (`create_reminder` notified_at reset) |
| HA resolves wrong device | `homeassistant.py` (`_normalize_ar`, domain hints in `resolve_entity`) |
| HA automation in reminders | `tool_calling.py` (`is_ha_automation` flag), `graph.py` (`query_reminders` filter) |
| Stream skips tool calls | `tool_calling.py` (`chat_stream` — tool_calls_found must precede streamed_text check) |
| HA webhook not notifying | `routers/homeassistant.py` (`ha_webhook`), Telegram bot token |
| OWUI voice no audio / TTS 401 | Docker env vars (`AUDIO_TTS_*`), ElevenLabs API key (must be unrestricted) |
| OWUI STT bad transcription | `scripts/deepgram_stt_proxy.py`, `rag-stt-proxy` service, Deepgram params |
| OWUI voice not concise | `openwebui_pipe.py` (`_is_voice_mode`, `voice_concise` Valve) |
| OpenClaw report not saving | `routers/openclaw.py` (`openclaw_report`), `retrieval.py` (`ingest_text`) |
| Water report missing from morning | `telegram_bot.py` (`job_morning_summary`), `routers/proactive.py` (`latest_water_report`) |
| OpenClaw critical not notifying | `routers/openclaw.py` (severity check, `_get_bot_token`) |
