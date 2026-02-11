# Architecture

## Overview

Personal Life RAG is a bilingual (Arabic/English) personal life management system. It combines a Knowledge Graph (FalkorDB), Vector Search (Qdrant), and an LLM (Qwen3-VL via vLLM) into an Agentic RAG pipeline that understands natural Arabic queries and manages finances, reminders, projects, tasks, knowledge, and more.

```
                      +------------------+
                      |   User (Arabic)  |
                      +--------+---------+
                               |
                      +--------v---------+
                      |   FastAPI :8500   |
                      |  (Routers Layer)  |
                      +--------+---------+
                               |
                 +-------------v--------------+
                 |     RetrievalService        |
                 |  (Agentic RAG Pipeline)     |
                 +--+------+------+------+----+
                    |      |      |      |
            +-------v+  +--v---+ +v-----+ +v---------+
            | LLM    |  |Graph | |Vector| | Memory   |
            | Service|  |Svc   | |Svc   | | Service  |
            +---+----+  +--+---+ +--+---+ +----+-----+
                |           |        |          |
            +---v----+  +---v---+ +--v----+ +---v-----+
            | vLLM   |  |Falkor | |Qdrant | | Redis   |
            | :8000  |  |DB     | | :6333 | | :6380   |
            |Qwen3-VL|  | :6379 | |BGE-M3 | | Memory  |
            +--------+  +-------+ +-------+ +---------+
```

## Services

### 1. LLM Service (`app/services/llm.py`)
- Connects to vLLM (OpenAI-compatible API) on port 8000
- Model: **Qwen3-VL-32B-Instruct** (90K context, vision-capable)
- Functions: translate (AR<>EN), extract facts (with NER hints), classify input, think/reflect (agentic), vision analysis, clarification checking, core memory extraction, daily summarization
- Streaming: `chat_stream()` parses SSE from vLLM, `generate_response_stream()` yields token chunks
- Conversation summarization: `summarize_conversation()` — Arabic summary, temperature 0.3, max 500 tokens
- `enable_thinking: False` in chat_template_kwargs to avoid Qwen3 thinking tokens

### 2. Graph Service (`app/services/graph.py`)
- **FalkorDB** (Redis-based graph database) on port 6379
- Stores structured entities: Person, Company, Project, Task, Idea, Topic, Tag, Expense, Debt, Reminder, Knowledge, File, Item, Location
- Entity relationships via Cypher queries (STORED_IN, FROM_PHOTO, INVOLVES, BELONGS_TO, TAGGED_WITH, etc.)
- **Entity resolution**: `resolve_entity_name()` — embeds name in Qdrant, searches for similar existing entities, uses canonical name if match above threshold (Person: 0.85, default: 0.80). Stores aliases on canonical node's `name_aliases` list
- **Smart tags**: `_normalize_tag()` with English→Arabic aliases, vector dedup at 0.85 threshold, `tag_entity()` for TAGGED_WITH relationships
- **Knowledge auto-categorization**: `_guess_knowledge_category()` keyword heuristic + automatic TAGGED_WITH linking
- **Multi-hop traversal**: `query_entity_context()` with configurable depth (default 3 hops), selective 3rd hop limited to key relationship types
- Dedicated query methods: financial summary/reports, debt management, reminders (CRUD + merge duplicates), daily planner, projects overview, knowledge search, active tasks, inventory queries, item movement
- `upsert_from_facts()` — auto-handles all entity types from LLM extraction, resolves relationship targets, routes Tag targets to `tag_entity()`
- Idea similarity detection: new ideas get embedded and linked via `SIMILAR_TO` edges

### 3. Vector Service (`app/services/vector.py`)
- **Qdrant** vector database on port 6333
- Embedding model: **BAAI/bge-m3** (1024-dim, loaded on GPU, ~3GB VRAM)
- Stores enriched text chunks with metadata
- Supports filtered search by source_type, entity_type, topic

### 4. Memory Service (`app/services/memory.py`)
- **Redis** (separate instance) on port 6380
- 3-layer memory architecture:
  - **Layer 1 — Working Memory**: last N message pairs (Redis List, 24h TTL)
  - **Layer 2 — Daily Summary**: compressed daily summary (7-day TTL)
  - **Layer 3 — Core Memory**: user preferences/patterns (permanent Redis Hash)
- Pending actions storage for delete/cancel confirmation flow (300s TTL)
- Message counter for triggering periodic tasks
- Conversation compression: `compress_working_memory()` returns old messages, `LTRIM` to keep recent
- Conversation summary: `conversation_summary:{session_id}` Redis key with 24h TTL

### 5. File Service (`app/services/files.py`)
- Processes uploaded files: images, PDFs, audio
- Images: vLLM Vision API (classify type, then type-specific analysis)
- PDFs: pymupdf4llm for markdown extraction
- Audio: WhisperX (large-v3-turbo, `language="ar"`, loaded on-demand, serialized via asyncio.Lock)
- PyTorch 2.6 compatibility: patches `torch.load` to handle `weights_only=None` for omegaconf checkpoints
- Files stored at `data/files/{hash[:2]}/{hash}.{ext}`
- **Content-addressed dedup**: SHA256 hash check before processing — skips duplicates
- **Audio = transcription only**: no fact extraction, caller sends transcript to `/chat/` for full processing
- Auto-expense: invoice images with total > 0 auto-create Expense nodes
- Auto-item: inventory photos → classify + analyze → `create_item_from_photo()` → upsert Item node + FROM_PHOTO edge
- Photo similarity: after auto-item, vector search for similar inventory items (score ≥ 0.5)

### 6. Retrieval Service (`app/services/retrieval.py`)
- Orchestrates the full Agentic RAG pipeline (see [Pipeline](#agentic-rag-pipeline))
- Smart keyword router for zero-latency routing
- Ingestion pipeline: translate > chunk > enrich > embed + extract facts
- Post-processing: fact extraction (with NER hints), periodic summaries, core memory extraction
- `_prepare_context()` — shared pipeline extracted for code reuse between sync and streaming
- `retrieve_and_respond_stream()` — yields NDJSON (meta, token chunks, done)
- Auto-compression: when working memory > 15 messages, summarize + keep 4 recent

### 7. Backup Service (`app/services/backup.py`)
- Full system backup: FalkorDB graph (nodes + edges → JSON), Qdrant (scroll all points → JSON), Redis (SCAN + type-specific dump → JSON)
- Restore: MERGE nodes/edges in graph, upsert Qdrant points, type-specific Redis SET/RPUSH/HSET
- Auto-cleanup: removes backups older than `backup_retention_days`
- Stores backups in `data/backups/{timestamp}/` (graph.json, vector.json, redis.json)

### 8. NER Service (`app/services/ner.py`)
- Arabic NER using HuggingFace `transformers` pipeline with `CAMeL-Lab/bert-base-arabic-camelbert-msa-ner`
- Lazy-loaded in ThreadPoolExecutor to avoid blocking startup
- Entity extraction with score >= 0.7 filter
- Mapping: PER→Person, LOC→Location, ORG→Organization
- `format_hints()` returns string like "Detected entities: Person: محمد; Location: الرياض"
- Hints prepended to extract prompt to guide LLM fact extraction

## Agentic RAG Pipeline

```
User Query (Arabic)
      |
      v
[Confirmation Pre-check] -- pending action? --> yes/no/number --> execute/cancel/disambiguate
      |
      v
[1. Translate AR -> EN]
      |
      v
[2. Smart Router (keywords)] -- match? --> fast path (skip Think)
      |                                         |
      v (no match)                              |
[3. THINK - LLM decides strategy]              |
      |                                         |
      v  <--------------------------------------+
[Delete Confirmation Gate] -- is_delete_intent()? --> store pending, return confirmation message
      |                        (only delete/cancel keywords trigger confirmation;
      |                         all other side-effects execute directly via post-processing)
      |
      v
[4. ACT - Execute retrieval strategy]
      |   graph_* routes: FalkorDB queries + hybrid vector search
      |   vector: Qdrant semantic search + graph fallback
      |   hybrid: both graph + vector
      |
      v
[5. REFLECT + Self-RAG] -- score chunks, filter below threshold (0.3)
      |
      v (if !sufficient)
[6. RETRY] -- flip strategy, merge results (max 1 retry)
      |
      v
[7. Build Context] -- system memory + conversation turns + filtered chunks (<=15K tokens)
      |
      v
[8. Generate Response] -- multi-turn Arabic response
      |
      v
[9. Post-process (background)] -- fact extraction, memory updates, periodic tasks
```

## Smart Router

Zero-latency keyword-based routing, checked in specificity order:

| Priority | Route | Triggers (AR/EN) |
|----------|-------|-------------------|
| 1 | `graph_debt_payment` | سدد، رجع الفلوس، paid back |
| 2 | `graph_debt_summary` | ديون، يطلبني، who owe |
| 3 | `graph_financial_report` | ملخص، تقرير، monthly spend |
| 4 | `graph_financial` | صرفت، دفعت، مصاريف |
| 5 | `graph_reminder_action` | خلصت + تذكير، done + reminder |
| 6 | `graph_reminder` | ذكرني، موعد، remind |
| 7 | `graph_daily_plan` | رتب يومي، خطة اليوم، plan my day |
| 8 | `graph_knowledge` | وش أعرف، معلومة، what do I know |
| 9 | `graph_sprint` | سبرنت، burndown، velocity |
| 10 | `graph_focus_stats` | focus، pomodoro، بومودورو، تركيز |
| 11 | `graph_timeblock` | رتب.*وقت، جدول.*مهام، time block |
| 12 | `graph_productivity_report` | إنتاجية، productivity stats |
| 13 | `graph_project` | مشروع، project، progress |
| 14 | `graph_person` | مين، who، person |
| 15 | `graph_task` | مهمة، مهام، task، todo |
| 16 | `graph_inventory_duplicates` | أغراض مكررة، duplicate item |
| 17 | `graph_inventory_report` | تقرير مخزون، inventory report |
| 18 | `graph_inventory` (move) | نقلت، حركت، حطيته في، moved، relocated |
| 19 | `graph_inventory` (usage) | استخدمت، ضاع، خلص، عطيت، انكسر |
| 20 | `graph_inventory_unused` | ما استخدمت، مهمل، unused |
| 21 | `graph_inventory` (query) | مخزون، أغراضي، وين ال، inventory |
| 22 | `llm_classify` | fallback to LLM classification |

## Data Flow: Ingestion

```
Text/File Upload
      |
      v
[Translate AR -> EN]
      |
      +---> [Chunk text (500 tokens, 50 overlap)]
      |         |
      |         v
      |     [Contextual Enrichment (LLM adds doc context per chunk)]
      |         |
      |         v
      |     [Embed via BGE-M3 -> Qdrant]
      |
      +---> [Extract Facts (LLM)]
                |
                v
            [Upsert to FalkorDB (entities + relationships)]
```

## Configuration

All settings are in `app/config.py` via Pydantic `BaseSettings` (overridable via `.env`):

| Setting | Default | Description |
|---------|---------|-------------|
| `vllm_base_url` | `http://localhost:8000/v1` | vLLM API endpoint |
| `vllm_model` | `Qwen/Qwen3-VL-32B-Instruct` | LLM model name |
| `falkordb_port` | 6379 | FalkorDB port |
| `qdrant_port` | 6333 | Qdrant port |
| `redis_port` | 6380 | Redis memory port |
| `bge_model_name` | `BAAI/bge-m3` | Embedding model |
| `bge_device` | `cuda` | Embedding device |
| `bge_dimension` | 1024 | Embedding dimension |
| `api_port` | 8500 | FastAPI port |
| `working_memory_size` | 5 | Message pairs in working memory |
| `max_context_tokens` | 15000 | Token budget for LLM context |
| `self_rag_threshold` | 0.3 | Minimum chunk relevance score |
| `agentic_max_retries` | 1 | Max retrieval retries |
| `confirmation_enabled` | True | Enable confirmation flow (delete/cancel intents only) |
| `confirmation_ttl_seconds` | 300 | Pending action TTL |
| `daily_summary_interval` | 10 | Messages between daily summaries |
| `core_memory_interval` | 20 | Messages between core memory extraction |
| `whisperx_model` | `large-v3-turbo` | WhisperX model |
| `whisperx_language` | `ar` | WhisperX language (Arabic) |
| `telegram_bot_token` | `""` | Telegram Bot API token |
| `tg_chat_id` | `""` | Authorized Telegram user ID |
| `mcp_port` | 8600 | MCP server port |
| `timezone_offset_hours` | 3 | User timezone offset (UTC+3 = Riyadh) |
| `proactive_enabled` | True | Enable/disable proactive scheduler |
| `proactive_morning_hour` | 7 | Morning summary local hour |
| `proactive_noon_hour` | 13 | Noon check-in local hour |
| `proactive_evening_hour` | 21 | Evening summary local hour |
| `proactive_reminder_interval_min` | 30 | Reminder check interval (minutes) |
| `proactive_alert_interval_hours` | 6 | Smart alerts interval (hours) |
| `proactive_stalled_days` | 14 | Days threshold for stalled projects |
| `proactive_old_debt_days` | 30 | Days threshold for old debts |
| `entity_resolution_enabled` | True | Enable/disable entity resolution |
| `entity_resolution_person_threshold` | 0.85 | Similarity threshold for Person dedup |
| `entity_resolution_default_threshold` | 0.80 | Similarity threshold for other entity types |
| `graph_max_hops` | 3 | Max hops for graph context traversal |
| `inventory_unused_days` | 90 | Days threshold for unused item detection |
| `inventory_report_top_n` | 10 | Max items in "top by quantity" report section |
| `energy_peak_hours` | `"9,10,11"` | Peak energy hours for time-blocking |
| `energy_low_hours` | `"14,15"` | Low energy hours for time-blocking |
| `work_day_start` | 8 | Work day start hour |
| `work_day_end` | 18 | Work day end hour |
| `pomodoro_default_minutes` | 25 | Default pomodoro duration |
| `sprint_default_weeks` | 2 | Default sprint length |
| `backup_enabled` | True | Enable/disable backup system |
| `backup_hour` | 3 | Daily backup hour (local time) |
| `backup_retention_days` | 30 | Days to keep backups |
| `backup_dir` | `"data/backups"` | Backup storage directory |
| `arabic_ner_enabled` | True | Enable/disable Arabic NER |
| `arabic_ner_model` | `"CAMeL-Lab/..."` | HuggingFace NER model name |
| `conversation_compress_threshold` | 15 | Compress when messages exceed this |
| `conversation_compress_keep_recent` | 4 | Messages to keep after compression |

## Interfaces (Phase 5)

Three client interfaces provide access from mobile, browser, and Claude Desktop — all calling the RAG API at port 8500.

```
                  ┌───────────────┐
                  │  Telegram Bot │  (aiogram 3.x — polling)
                  │  text/voice/  │
                  │  photo/docs   │
                  └──────┬────────┘
                         │
  ┌───────────────┐      │      ┌───────────────┐
  │  Open WebUI   │      │      │  MCP Server   │
  │  Tools        ├──────┼──────┤  :8600 (SSE)  │
  │  (Docker)     │      │      │  (FastMCP)    │
  └──────┬────────┘      │      └──────┬────────┘
         │               │             │
         └───────────────┼─────────────┘
                         │
                ┌────────▼─────────┐
                │   FastAPI :8500   │
                │   (RAG API)      │
                └──────────────────┘
```

### Telegram Bot (`app/integrations/telegram_bot.py`)
- Standalone async process (not inside FastAPI)
- Calls RAG API via `httpx.AsyncClient`
- Auth: only responds to configured `TG_CHAT_ID`
- Session ID: `tg_{user_id}` for per-user memory
- Features: text chat, voice→transcribe→chat, photo→analyze→Arabic summary via LLM, document→processing
- Voice flow: `/ingest/file` (transcription only) → transcript sent to `/chat/` for response + fact extraction
- Photo flow: `/ingest/file` (classify + analyze) → analysis sent to `/chat/` for Arabic summary
- Photo captions: user context passed to Vision prompt for focused analysis
- File dedup: duplicate files get "الملف موجود مسبقاً" message
- Inline keyboard buttons for delete/cancel confirmation flow (yes/no)
- Commands: `/start`, `/plan`, `/debts`, `/reminders`, `/projects`, `/tasks`, `/report`
- Message splitting for Telegram's 4096 char limit

### Open WebUI Tools (`app/integrations/openwebui_tools.py`)
- Standalone Python file — copy into Open WebUI Admin → Functions (type: Tool)
- Sync `requests` (Open WebUI runs tools synchronously)
- API URL: `http://host.docker.internal:8500` (Docker → host)
- 21 tools (v1.5): chat, store_document, search_knowledge, get_financial_report, get_debts, get_reminders, delete_reminder, update_reminder, delete_all_reminders, merge_duplicate_reminders, get_projects, get_tasks, daily_plan, get_inventory, get_inventory_report, get_sprints, get_focus_stats, create_backup, list_backups, get_graph_schema, get_graph_stats
- `store_document` stores text via `/ingest/text` and returns extracted entities detail (chunks, facts, entity list)
- Configurable via Valves (api_base_url, session_id)

### Open WebUI Filter (`app/integrations/openwebui_filter.py`)
- Standalone Python file — copy into Open WebUI Admin → Functions (type: Filter)
- **Inlet filter** (v1.3): injects current date/time (Arabic) + timezone into system prompt
- Solves: Open WebUI LLM doesn't know the current date → hallucinated wrong dates
- Includes Arabic day/month names, "بكرة" = tomorrow's date
- **Anti-lying STATUS rules**: instructs LLM to only say "done" when `STATUS: ACTION_EXECUTED` is present; prevents fabricating results
- **Auto file-upload detection**: `_has_files()` checks body-level files, message-level files/images, and citation markers
- When files detected, injects mandatory store_document instruction (full text, not summary)
- Configurable via Valves (timezone_offset, prepend_date, arabic_context)

### MCP Server (`mcp_server.py`)
- Standalone process using FastMCP (SSE transport) on port 8600
- Async `httpx` client to RAG API
- 24 tools: chat, search, create_reminder, record_expense, get_financial_report, get_debts, get_reminders, delete_reminder, update_reminder, delete_all_reminders, merge_duplicate_reminders, get_projects, get_tasks, get_knowledge, daily_plan, ingest_text, get_inventory, get_inventory_report, get_sprints, get_focus_stats, create_backup, list_backups, get_graph_schema, get_graph_stats

## Proactive System (Phase 6)

APScheduler runs inside the Telegram bot process with 5 scheduled jobs:

| Job | Schedule | Description |
|-----|----------|-------------|
| Morning Summary | Cron 07:00 | Daily plan + spending alerts |
| Noon Check-in | Cron 13:00 | Overdue reminders (skips if empty) |
| Evening Summary | Cron 21:00 | Completed today + tomorrow's reminders |
| Reminder Check | Every 30 min | Due reminders → send + advance recurring |
| Smart Alerts | Every 6 hours | Stalled projects + old debts (skips if empty) |

Jobs call 7 REST endpoints under `/proactive/*` on the FastAPI server. Local hours are converted to UTC for CronTrigger.

## Inventory System (Phase 7)

```
Photo (Telegram)
      |
      v
[File Classify] -- inventory_item? --> [Vision Analyze (inventory)]
      |                                         |
      v                                         v
[Other types...]                  [create_item_from_photo()]
                                          |
                                    +-----+-----+
                                    |           |
                                    v           v
                              [upsert_item]  [Qdrant embed]
                              (FalkorDB)     (source_type=file_inventory_item)
                                    |
                                    v
                              [Similar items search]
                              (vector, score ≥ 0.5)
```

Features:
- **Item/Location nodes** in FalkorDB with hierarchical locations (building > room > shelf > box)
- **Location normalization**: English→Arabic aliases, `>` separator, space collapsing
- **Category normalization**: `_CATEGORY_ALIASES` maps English/Arabic variants to canonical Arabic
- **ItemUsage pseudo-entity**: "استخدمت/ضاع/عطيت" → quantity reduction (clamped at 0)
- **ItemMove pseudo-entity**: "نقلت/حركت" → delete old STORED_IN, create new
- **Purchase alert**: confirmed Expense → `find_similar_items()` → "⚠️ عندك في المخزون"
- **Photo similarity**: vector search after auto-item for similar existing items

## Advanced Inventory (Phase 9)

- **QR/Barcode scanning**: `_scan_barcodes(file_bytes)` uses pyzbar + PIL on image bytes. Barcode value + type stored on Item node. `find_item_by_barcode()` for lookup
- **Last-use tracking**: `_touch_item_last_used(name)` fire-and-forget SET `last_used_at` on Item. Called from `adjust_item_quantity()`, `move_item()`, and `graph_inventory` route via `asyncio.create_task`
- **Unused items**: `query_unused_items(days)` finds items with no `last_used_at` or older than cutoff
- **Inventory report**: `query_inventory_report()` — 7 sub-queries (totals, by category, by location, by condition, without location, unused count, top by quantity)
- **Duplicate detection**: `detect_duplicate_items()` — Cypher name-overlap; `detect_duplicate_items_vector()` — embedding similarity ≥ 0.8
- **Telegram**: `/inventory report` subcommand with `_format_inventory_report_ar()` Arabic formatter

## Smart Knowledge + Entity Resolution (Phase 8)

### Entity Resolution
```
upsert_person("Mohamed")
      |
      v
[resolve_entity_name("Mohamed", "Person")]
      |
      v
[Qdrant search: entity_type="Person", limit=3]
      |
      v
[Match: "Mohammed" (score=0.89) >= threshold (0.85)]
      |
      v
[_store_alias("Person", "name", "Mohammed", "Mohamed")]
      |
      v
[Return "Mohammed" → MERGE uses canonical name]
```

- Resolves Person, Company, Project, Topic, Knowledge entities
- Skips Expense, Debt, Reminder, Item, Idea, Tag (transactional/unique entities)
- Also resolves relationship targets in `upsert_from_facts()`
- Configurable thresholds: Person 0.85 (stricter), default 0.80

### Smart Tags
- `_TAG_ALIASES` maps English→Arabic (e.g. "programming" → "برمجة", "tech" → "تقنية")
- `upsert_tag()` normalizes + vector dedup (0.85 threshold) before creating
- `tag_entity()` creates TAGGED_WITH relationship between any entity and a tag
- Tag targets in extraction relationships are automatically routed to `tag_entity()`

### Knowledge Auto-categorization
- `_guess_knowledge_category()` keyword heuristic assigns categories (تقنية, طبخ, صحة, etc.)
- Applied in `_create_generic()` when no category is provided by LLM extraction
- Auto-tags Knowledge with its category via TAGGED_WITH

### Multi-hop Graph Traversal
- `query_entity_context(label, key_field, value)` with `graph_max_hops` (default 3)
- Hop 1-2: unrestricted traversal
- Hop 3: selective — only BELONGS_TO, INVOLVES, WORKS_AT, RELATED_TO, TAGGED_WITH, STORED_IN, SIMILAR_TO
- `query_person_context` and `query_project_context` delegate to `query_entity_context`
- `graph_person` route tries person context first, falls back to `search_nodes`

## Productivity System (Phase 10)

### Sprints
- Sprint CRUD: create, update, assign tasks, query, complete
- Sprint burndown: ideal vs actual remaining tasks, days passed, progress %
- Sprint velocity: avg tasks/week across completed sprints
- Sprint entity in extract prompt, auto-handled in `upsert_from_facts`

### Focus Sessions (Pomodoro)
- FocusSession nodes in FalkorDB with start/end time, duration, task link
- Stats: total sessions, total minutes, avg duration, completion rate

### Time-Blocking
- Energy-aware scheduling: peak hours → high energy tasks, low hours → low energy tasks
- `suggest_time_blocks(date, energy_profile)` generates schedule from unfinished tasks
- `apply_time_blocks(blocks, date)` sets start_time/end_time on Task nodes

### Task Enhancements
- New fields: `estimated_duration`, `energy_level`, `start_time`, `end_time`
- Auto-link Task→Project via name substring matching after creation
- Progress: `query_projects_overview` shows % complete + ETA based on 3-week velocity

## Infrastructure (Phase 11)

### Backup System
```
Daily (3 AM) or manual trigger
      |
      v
[BackupService.create_backup()]
      |
      +---> [_backup_graph()] — MATCH (n) + MATCH ()-[r]->() → graph.json
      |
      +---> [_backup_qdrant()] — scroll all points (batch=100) → vector.json
      |
      +---> [_backup_redis()] — SCAN + type-specific dump → redis.json
      |
      v
data/backups/{timestamp}/
      |
      v
[cleanup_old_backups()] — remove > 30 days
```

### Arabic NER Pipeline
```
User Query (Arabic)
      |
      v
[NERService.extract_entities()]
      |  CAMeL-Lab/bert-base-arabic-camelbert-msa-ner
      |  Filter: score >= 0.7
      |  Map: PER→Person, LOC→Location, ORG→Organization
      |
      v
[format_hints()] → "Detected entities: Person: محمد; Location: الرياض"
      |
      v
[Prepended to extract prompt] → guides LLM fact extraction
```

### Streaming (NDJSON)
```
POST /chat/stream
      |
      v
[_prepare_context()] — shared pipeline (translate, route, act, reflect, retry)
      |
      v
[generate_response_stream()] → vLLM SSE → token chunks
      |
      v
NDJSON lines:
  {"type":"meta", "route":..., "sources":...}
  {"type":"token", "content":"مهام"}
  {"type":"token", "content":"ك اليوم:"}
  ...
  {"type":"done"}
```

### Conversation Compression
```
Working memory > 15 messages?
      |
      v (yes)
[compress_working_memory()] → returns old messages, LTRIM keeps 4 recent
      |
      v
[summarize_conversation()] → Arabic summary (temperature 0.3, max 500 tokens)
      |
      v
[save_conversation_summary()] → Redis key with 24h TTL
      |
      v
[Included in context building for subsequent queries]
```

### Graph Visualization
- JSON export: full graph, by entity type, or ego-graph (center + N hops)
- Server-side PNG via networkx + matplotlib
- Color palette by node type (Person=blue, Project=orange, Task=green, etc.)
- Spring layout with adaptive k parameter based on node count
