# Progress Tracker

## Completed Phases

### Phase 1 — Core RAG System
- [x] FastAPI app with lifespan startup/shutdown
- [x] vLLM integration (Qwen3-VL-32B-Instruct)
- [x] FalkorDB graph service (entities: Person, Company, Project, Task, Idea, Topic, Tag)
- [x] Qdrant vector service (BGE-M3 embeddings, 1024-dim)
- [x] Redis 3-layer memory (working, daily summary, core)
- [x] Arabic<>English translation via LLM
- [x] Text ingestion pipeline (translate > chunk > enrich > embed + extract facts)
- [x] Contextual Retrieval (LLM adds document context to each chunk)
- [x] Fact extraction and graph upsert
- [x] Basic chat endpoint with RAG response generation
- [x] Search endpoint (vector/graph/auto)
- [x] Text ingestion endpoint

### Phase 2 — Agentic RAG + File Processing
- [x] Think > Act > Reflect pipeline with Self-RAG chunk scoring
- [x] Smart keyword router (zero-latency fast path)
- [x] Max 1 retry (flip strategy if Reflect says insufficient)
- [x] Image processing (vLLM Vision: classify type > analyze)
- [x] PDF processing (pymupdf4llm markdown extraction)
- [x] Audio processing (WhisperX on-demand, serialized via Lock)
- [x] File storage (content-addressed: `data/files/{hash[:2]}/{hash}.{ext}`)
- [x] File node in graph + relationships
- [x] Agentic trace in ChatResponse for observability

### Phase 3 — Financial System + Smart Reminders
- [x] Expense tracking (create, category breakdown, monthly reports)
- [x] Debt management (upsert, payment recording, partial status, disambiguation)
- [x] Spending alerts (40% above 3-month average)
- [x] Month-over-month comparison
- [x] 5 reminder types (one_time, recurring, persistent, event_based, financial)
- [x] Reminder actions (done, snooze, cancel)
- [x] Finer-grained smart router (debt_payment > debt_summary > financial_report > financial)
- [x] DebtPayment pseudo-entity in extraction
- [x] Auto-expense from invoice images
- [x] Category guessing heuristic (keyword-based, no LLM)
- [x] REST endpoints: /financial/report, /debts, /debts/payment, /alerts, /reminders/, /reminders/action, /reminders/update, /reminders/delete, /reminders/delete-all, /reminders/merge-duplicates

### Phase 4a — Smarter Conversations
- [x] Confirmation flow for side-effect routes ~~(financial, debt_payment, reminder)~~ → **now delete/cancel intents only** (see Reminder Management section)
- [x] Pending actions in Redis with 300s TTL
- [x] Action vs Query detection (heuristic pattern matching)
- [x] Disambiguation for multiple matching debts
- [x] Multi-turn conversation history (actual message turns, not flattened)
- [x] Token budget management (memory + history + context <= 15K)
- [x] Clarification prompts (missing required fields)
- [x] Periodic tasks: daily summary (every 10 msgs), core memory extraction (every 20 msgs)
- [x] Post-processing dedup (query extraction vs combined extraction)

### Phase 4b — Daily Planner, Projects, Knowledge, GraphRAG
- [x] Daily planner aggregation (reminders + tasks + debts I owe)
- [x] Projects overview with task progress (done/total)
- [x] Knowledge node querying with topic filter
- [x] Active tasks with project links and status filter
- [x] Idea similarity detection (vector search + SIMILAR_TO edges)
- [x] Smart router: `graph_daily_plan`, `graph_knowledge` keywords
- [x] Agentic prompts updated with new strategies
- [x] REST endpoints: /projects/, /projects/update, /tasks/, /knowledge/
- [x] `_build_set_clause` bug fix (variable name mismatch)

### Phase 5 — Interfaces (Telegram + Open WebUI + MCP)
- [x] Telegram Bot (aiogram 3.x, polling, text/voice/photo/document)
- [x] Telegram commands: /start, /plan, /debts, /reminders, /projects, /tasks, /report
- [x] Telegram auth (TG_CHAT_ID single-user), message splitting (4096 char limit)
- [x] Inline keyboard for confirmation flow (yes/no buttons)
- [x] Open WebUI tools file (8 tools: chat, search, financial, debts, reminders, projects, tasks, daily plan)
- [x] MCP server (FastMCP, SSE on port 8600, 24 tools)
- [x] MCP tools: chat, search, create_reminder, record_expense, financial report, debts, reminders, delete_reminder, update_reminder, delete_all_reminders, merge_duplicate_reminders, projects, tasks, knowledge, daily plan, ingest text, inventory, inventory report, sprints, focus stats, backup, list backups, graph schema, graph stats
- [x] Startup scripts: start_telegram.sh, start_mcp.sh
- [x] Config: telegram_bot_token, tg_chat_id, mcp_port in Settings + .env

### Phase 5 — Bug Fixes & Improvements (Testing)
- [x] **Photo Arabic replies**: تحليل الصور يمر عبر `/chat/` لترجمة كاملة بالعربي (بدل labels إنجليزية)
- [x] **Caption context**: كابشن المستخدم يُمرر لـ Vision prompt للتركيز على المحتوى المهم
- [x] **Concise summaries**: prompt محسّن يطلب 2-3 أسطر بدون وصف الخلفية والإضاءة
- [x] **File dedup**: فحص SHA256 hash قبل المعالجة — يتخطى الملفات المكررة
- [x] **FalkorDB CREATE syntax**: إصلاح `_create_generic` و `create_idea` — `{k}: ${k}` بدل `n.{k} = ${k}`
- [x] **FalkorDB primitive types**: تحويل dict→str و list[dict]→list[str] قبل التخزين
- [x] **WhisperX variable scope**: تهيئة `model=None` و `audio=None` قبل try/finally
- [x] **PyTorch 2.6 weights_only**: patch `torch.load` لمعالجة `weights_only=None` → `False` (لـ omegaconf checkpoints)
- [x] **ffmpeg dependency**: إضافة ffmpeg كمتطلب نظام لـ WhisperX
- [x] **WhisperX Arabic**: تحديد `language="ar"` لتحسين دقة التعرف على الكلام
- [x] **Voice = chat**: الصوت يُحوّل لنص فقط عبر `/ingest/file` ثم يُرسل لـ `/chat/` للرد (بدون تخزين مكرر)
- [x] **System prompt date/time**: إضافة التاريخ والوقت الحالي (توقيت الرياض UTC+3) للـ system prompt
- [x] **Extract prompt date**: إضافة التاريخ لـ extract prompt لحل التواريخ النسبية ("بكرة" → التاريخ الصحيح)
- [x] **Timezone config**: `timezone_offset_hours` في Settings (default 3 = Asia/Riyadh)
- [x] **Debt direction normalization**: `_normalize_direction()` يحول `owed_by_me`/`owed_to_other` → `i_owe` (الـ LLM يولد قيم غير متسقة)
- [x] **Extract prompt "I owe" example**: مثال لتعليم الـ LLM يستخدم `i_owe` بدل اختراع قيم
- [x] **Bot error handler**: `@router.error()` يرسل رسالة خطأ للمستخدم عند أي exception

### Phase 5 — Testing Results (46/48 passed)
- [x] Telegram Bot: 20/20 (أوامر، نصوص عربي/إنجليزي، صور، صوت، PDF، ملفات غير مدعومة)
- [x] MCP Server: 14/14 (12 tool + startup + registration)
- [x] Open WebUI: 2/4 (syntax + instantiation OK — اختبار مباشر يحتاج Docker)
- [x] اختبارات عامة: 10/10 (تواريخ، sessions، timeouts، errors، splitting)

### Phase 6 — Proactive System (Scheduled Notifications + Smart Alerts)
- [x] APScheduler (AsyncIOScheduler) in Telegram bot process
- [x] 5 scheduled jobs: morning summary (cron 07:00), noon check-in (cron 13:00), evening summary (cron 21:00), reminder check (30min interval), smart alerts (6h interval)
- [x] Local-to-UTC hour conversion for CronTrigger
- [x] Graceful scheduler shutdown in `finally` block
- [x] 7 REST endpoints under `/proactive/*` (morning-summary, noon-checkin, evening-summary, due-reminders, advance-reminder, stalled-projects, old-debts)
- [x] `advance_recurring_reminder()` in graph service (daily/weekly/monthly/yearly via dateutil.relativedelta)
- [x] 6 Arabic formatters for Telegram messages
- [x] 5 async job functions with try/except (noon check-in + smart alerts skip if empty)
- [x] Stalled projects detection (active projects with no task update in N days)
- [x] Old debts detection (debts I owe older than N days)
- [x] 8 `proactive_*` settings in config.py (enabled, hours, intervals, thresholds)
- [x] Dependencies: apscheduler>=3.10.0, python-dateutil>=2.9.0

### Phase 6 — Testing Results (27/27 passed, total 73/75)
- [x] Proactive endpoints: 7/7 (all returning correct data)
- [x] Scheduler: 4/4 (5 jobs registered, UTC conversion, startup log)
- [x] Fire tests: 3/3 (morning + evening sent to Telegram, smart alerts correctly skipped)
- [x] Graph/Config: 3/3 (advance_recurring_reminder, relativedelta, config settings)
- [x] Regression: 10/10 (all existing endpoints unaffected)

### Phase 7a — Core Inventory System
- [x] كيانات `Item` + `Location` في FalkorDB (هرمي: مبنى > غرفة > رف > كرتون)
- [x] تصوير الغرض عبر تلقرام → Vision يحلل (اسم، ماركة، مواصفات، فئة، حالة)
- [x] Auto-item creation from photos (`create_item_from_photo()` in files.py)
- [x] تخزين الكمية والمكان بالعربي ("السطح > الرف الثاني > الكرتون الأزرق")
- [x] Location normalization (`_normalize_location()`) — English→Arabic aliases, `>` separator, space collapsing
- [x] بحث المخزون: "وين الـ X؟" / "عندي X؟" / "كم كيبل USB عندي؟"
- [x] أمر `/inventory` في تلقرام (عرض، بحث، إحصائيات)
- [x] REST endpoints: GET `/inventory/`, `/inventory/summary`, POST `/inventory/item`, PUT `/inventory/item/{name}/location`, PUT `/inventory/item/{name}/quantity`
- [x] Smart router keywords: مخزون/أغراضي/وين ال/inventory → `graph_inventory`
- [x] `inventory_item` type added to file_classify + vision prompts
- [x] File dedup enhancement: duplicate photo + caption → enriches query with item name
- [x] `find_item_by_file_hash()` + GET `/inventory/by-file/{hash}` — lookup via FROM_PHOTO relationship

### Phase 7b — Inventory Usage + Interactions
- [x] ItemUsage pseudo-entity in extract prompt ("استخدمت/ضاع/عطيت" → quantity reduction)
- [x] `adjust_item_quantity(name, -delta)` — clamps at 0
- [x] INVENTORY_USAGE_KEYWORDS checked before INVENTORY_KEYWORDS in smart_route
- [x] Clarification skip: extraction found entities → skip clarification LLM
- [x] Bot asks "وين حاطه؟" on captionless inventory photos — pending location with 5-min TTL
- [x] `upsert_item` always returns existing location even when no new location passed

### Phase 7c — Smart Inventory
- [x] ItemMove pseudo-entity: "نقلت/حركت/حطيته في/moved/relocated" → `move_item()` deletes old STORED_IN, creates new
- [x] INVENTORY_MOVE_KEYWORDS checked before INVENTORY_USAGE_KEYWORDS in smart_route
- [x] Confirmation message: "تبيني أنقل {name} من {from} إلى {to}؟"
- [x] Purchase duplicate alert: on confirmed Expense, `find_similar_items()` checks inventory → appends "⚠️ تنبيه: عندك في المخزون: ..."
- [x] Photo similarity search: after auto_item creation, vector search `source_type="file_inventory_item"` (score ≥ 0.5, top 3)
- [x] Photo search mode: duplicate photo with search keywords → POST `/inventory/search-similar` → shows matches
- [x] REST: POST `/inventory/search-similar` (vector search with score ≥ 0.4)
- [x] Category normalization: `_normalize_category()` — `_CATEGORY_ALIASES` dict maps English/Arabic variants to canonical Arabic

### Phase 7 — Testing Results (4/4 manual tests passed)
- [x] Item movement: confirmation + execution → STORED_IN updated
- [x] Purchase duplicate alert: confirmed expense → inventory warning shown
- [x] Search similar items: vector search returns scored results
- [x] Category normalization: "cables" → "إلكترونيات"

### Phase 8 — Smart Knowledge + Entity Resolution
- [x] Entity resolution via vector similarity (`resolve_entity_name()` — Person 0.85, default 0.80 threshold)
- [x] Alias storage: canonical node gets `name_aliases` list (e.g. "Mohammed" ← ["Mohamed"])
- [x] Resolution integrated into: upsert_person, upsert_project, upsert_company, upsert_topic, _create_generic, relationship targets
- [x] Smart Tags: `_TAG_ALIASES` dict (English→Arabic normalization) + `_normalize_tag()`
- [x] `upsert_tag()` returns canonical name, does vector dedup at 0.85 threshold
- [x] `tag_entity()` helper creates TAGGED_WITH relationship between any entity and a tag
- [x] Tag targets in `upsert_from_facts` relationship loop → routed to `tag_entity()` + continue
- [x] Knowledge auto-categorization: `_guess_knowledge_category()` keyword heuristic → `category` property
- [x] Knowledge auto-tagging: TAGGED_WITH → Tag(category) created automatically
- [x] Multi-hop graph traversal: `query_entity_context()` with configurable depth (`graph_max_hops`, default 3)
- [x] 3-hop query: selective hop 3 limited to BELONGS_TO/INVOLVES/WORKS_AT/RELATED_TO/TAGGED_WITH/STORED_IN/SIMILAR_TO
- [x] `_format_graph_context_3hop()` handles 10-column rows, deduplicates, limits to 30 lines
- [x] `query_person_context`/`query_project_context` delegate to `query_entity_context`
- [x] `graph_person` route in retrieval: tries person context (3-hop) first, falls back to `search_nodes`
- [x] 4 config settings: `entity_resolution_enabled`, `entity_resolution_person_threshold`, `entity_resolution_default_threshold`, `graph_max_hops`

### Phase 8 — Testing Results (5/5 passed)
- [x] Entity resolution: "Mohamed" → "Mohammed" (score 0.89), single Person node with `name_aliases: ["Mohamed"]`
- [x] Knowledge auto-categorization: "Python async code trick" → `category: "تقنية"`, TAGGED_WITH → Tag("تقنية")
- [x] Knowledge entity resolution: "Python async code handling trick" → "Python async code trick" (score 0.94)
- [x] Multi-hop chat: "tell me about Mohammed" → 3-hop graph context (person + company + debts)
- [x] Zero errors in API logs after all tests

### Phase 9 — Advanced Inventory
- [x] QR/Barcode scanning from photos (`pyzbar` + PIL on image bytes)
- [x] `_scan_barcodes(file_bytes)` in files.py, barcode/barcode_type stored on Item node
- [x] `find_item_by_barcode()` + GET `/inventory/by-barcode/{barcode}` — lookup by barcode value
- [x] Vision prompt: `barcode_visible` field added to inventory_item JSON template
- [x] Last-use tracking: `_touch_item_last_used(name)` — fire-and-forget SET `last_used_at`
- [x] Called from: `adjust_item_quantity()`, `move_item()`, `graph_inventory` route (via `asyncio.create_task`)
- [x] `query_unused_items(days)` — items with no `last_used_at` or older than cutoff
- [x] GET `/inventory/unused?days=N` — unused items endpoint
- [x] Comprehensive inventory report: `query_inventory_report()` — 7 sub-queries (totals, by category, by location, by condition, without location, unused count, top by quantity)
- [x] GET `/inventory/report` — inventory report endpoint
- [x] Telegram `/inventory report` subcommand with Arabic formatter
- [x] `_format_inventory_report()` in retrieval.py for RAG context
- [x] Duplicate detection: `detect_duplicate_items()` — Cypher name-overlap (`toLower CONTAINS`)
- [x] `detect_duplicate_items_vector()` — embedding similarity ≥ 0.8 on `file_inventory_item` vectors
- [x] GET `/inventory/duplicates?method=name|vector` — duplicate detection endpoint
- [x] Smart router: 3 new keyword patterns (duplicates > report > unused)
- [x] 2 new config settings: `inventory_unused_days` (90), `inventory_report_top_n` (10)
- [x] Dependency: `pyzbar>=0.1.9` + system `libzbar0`

### Phase 9 — Testing Results (6/6 passed)
- [x] GET `/inventory/report` → 200, comprehensive report (26 items)
- [x] GET `/inventory/unused?days=90` → 200, 19 unused items
- [x] GET `/inventory/duplicates` → 200, 14 name-overlap duplicates
- [x] GET `/inventory/duplicates?method=vector` → 200 (empty — expected)
- [x] GET `/inventory/by-barcode/1234567890` → 404 (correct, no barcodes stored yet)
- [x] Regression: existing inventory endpoints unaffected

---

### Phase 10 — Productivity Enhancements
- [x] Task enhancements: `estimated_duration`, `energy_level`, `start_time`, `end_time` fields on Task nodes
- [x] Energy normalization: `_normalize_energy()` maps aliases (deep/عالي→high, easy/سهل→low, etc.)
- [x] Sprint CRUD: `create_sprint`, `update_sprint`, `assign_task_to_sprint`, `query_sprint`, `complete_sprint`
- [x] Sprint velocity: `query_sprint_velocity()` — avg tasks/week across completed sprints
- [x] Sprint burndown: `query_sprint_burndown()` — ideal vs actual remaining, days passed, progress %
- [x] Focus sessions: `start_focus_session`, `complete_focus_session`, `query_focus_stats` — FocusSession nodes
- [x] Time-blocking: `suggest_time_blocks(date, energy_profile)` — peak→high, low→low energy tasks
- [x] `apply_time_blocks(blocks, date)` — SET start_time/end_time on Task nodes
- [x] Progress: `query_projects_overview` shows % complete + ETA based on 3-week velocity
- [x] Auto-link: Task→Project via name substring matching after creation
- [x] Sprint entity in extract prompt, auto-handled in `upsert_from_facts`
- [x] REST endpoints: /productivity/sprints/*, /productivity/focus/*, /productivity/timeblock/*
- [x] Telegram: `/focus` (start/done/stats), `/sprint` (list with progress bars)
- [x] Morning summary includes time-block suggestions
- [x] Smart router: sprint/burndown/velocity, focus/pomodoro, time-block, productivity stats routes
- [x] 6 config settings: `energy_peak_hours`, `energy_low_hours`, `work_day_start/end`, `pomodoro_default_minutes`, `sprint_default_weeks`

### Phase 10 — Testing Results (8/8 passed)
- [x] Sprint CRUD: create, list, assign task, burndown, velocity
- [x] Focus sessions: start, complete, stats
- [x] Time-blocking: suggest, apply
- [x] Telegram: /focus, /sprint commands
- [x] Regression: existing endpoints unaffected

### Phase 11 — Infrastructure Enhancements
- [x] **Backup System**: BackupService with `create_backup()`, `list_backups()`, `restore_backup()`, `cleanup_old_backups()`
- [x] Graph backup: Cypher MATCH nodes + edges → JSON
- [x] Qdrant backup: scroll all points in batches of 100 → JSON
- [x] Redis backup: SCAN + type-specific dump (STRING/LIST/HASH) with TTL preservation → JSON
- [x] Restore: MERGE nodes/edges, upsert Qdrant points, type-specific Redis SET/RPUSH/HSET
- [x] Backup retention: auto-cleanup backups older than `backup_retention_days` (default 30)
- [x] REST endpoints: POST /backup/create, GET /backup/list, POST /backup/restore/{timestamp}
- [x] Daily backup job in APScheduler at `backup_hour` UTC-adjusted
- [x] Telegram: `/backup` (create/list), notification on completion
- [x] **Arabic NER**: NERService with lazy-loaded HuggingFace `transformers` pipeline
- [x] Model: `CAMeL-Lab/bert-base-arabic-camelbert-msa-ner` (loaded in ThreadPoolExecutor)
- [x] Entity extraction: score >= 0.7 filter, PER→Person, LOC→Location, ORG→Organization mapping
- [x] NER hints prepended to extract prompt: `[NER hints: Person: محمد; Location: الرياض]`
- [x] Integrated in post-processing: runs on `query_ar`, passes hints to `extract_facts()`
- [x] **Conversation Summarization**: auto-compress at >15 messages, keeps 4 recent
- [x] Summary stored in Redis (`conversation_summary:{session_id}`, 24h TTL)
- [x] `summarize_conversation()` in LLM service (Arabic summary, temperature 0.3)
- [x] On-demand summary: GET /chat/summary
- [x] Summary included in context building when available
- [x] **Streaming**: NDJSON streaming for chat responses
- [x] `chat_stream()` in LLM — parses SSE from vLLM
- [x] `generate_response_stream()` — same system prompt, yields token chunks
- [x] `_prepare_context()` refactored from `retrieve_and_respond()` for code reuse
- [x] `retrieve_and_respond_stream()` yields NDJSON: `{"type":"meta"}`, `{"type":"token","content":"..."}`, `{"type":"done"}`
- [x] POST /chat/stream endpoint (StreamingResponse, application/x-ndjson)
- [x] Telegram streaming: `chat_api_stream()` edits placeholder message as tokens arrive
- [x] **Graph Visualization**: JSON export + server-side PNG generation
- [x] GET /graph/export (with entity_type/center/hops/limit filters)
- [x] GET /graph/schema (node labels + relationship types + counts)
- [x] GET /graph/stats (total nodes/edges, by-type counts)
- [x] POST /graph/image (PNG via networkx + matplotlib, color by node type)
- [x] Telegram: `/graph` (schema/type image/ego-graph image)
- [x] 7 config settings: `backup_enabled`, `backup_hour`, `backup_retention_days`, `backup_dir`, `arabic_ner_enabled`, `arabic_ner_model`, `conversation_compress_threshold`, `conversation_compress_keep_recent`
- [x] Dependencies: `networkx>=3.0`, `matplotlib>=3.8`

### Reminder Management (Post Phase 11)
- [x] **Reminder CRUD**: `delete_reminder(title)`, `delete_reminder_by_id(node_id)`, `update_reminder(title, ...)`, `delete_all_reminders(status)`
- [x] **Merge duplicates**: `merge_duplicate_reminders()` — exact-title dedup, keeps best (pending>snoozed, earliest due_date, lowest ID), merges best properties
- [x] REST endpoints: POST /reminders/update, /delete, /delete-all, /merge-duplicates (all POST for tool compatibility)
- [x] Schemas: `ReminderUpdateRequest`, `ReminderDeleteRequest` in models/schemas.py
- [x] Open WebUI tools: `delete_reminder`, `update_reminder`, `delete_all_reminders`, `merge_duplicate_reminders` (total: 20 tools)
- [x] MCP tools: same 4 tools (total: 24 tools)
- [x] **Confirmation flow: delete-only**: Changed from confirming all side-effect routes to confirming only delete/cancel intents. Adding expenses, reminders, inventory items, and debts now execute directly via post-processing without confirmation
- [x] `is_delete_intent()` in `app/prompts/conversation.py` — detects delete keywords (احذف/الغي/delete/remove/cancel/etc.)
- [x] `_extract_delete_target()` — strips delete keywords to get the target entity name
- [x] `_execute_delete_action()` — tries Arabic match first, then English translation for matching reminders
- [x] `DELETE_PATTERNS` regex added to `conversation.py` for robust delete keyword detection
- [x] **Anti-lying protocol**: STATUS prefix (ACTION_EXECUTED / PENDING_CONFIRMATION / CONVERSATION) on all chat tool responses
- [x] **Inventory routing fix**: Added purchase keywords (شريت/اشتريت/جبت/i bought/i got a/i have a), fixed `عندي` word boundary
- [x] **Item dedup fix**: Added `resolve_entity_name()` to `upsert_item()` — prevents duplicate Item nodes
- [x] `IngestResponse` schema: new `entities: list[dict]` field returns extracted entity details from `/ingest/text`
- [x] MCP `_current_date_context()` helper prepends date to every chat response
- [x] Duplicate cleanup: 45 reminders → 10 clean unique reminders (9 exact-match merged + 20 near-duplicates removed)

### Open WebUI Filter v2.0 + File Processing Improvements
- [x] **Filter v2.0** (`openwebui_filter.py`): Rewritten to directly process files via API instead of relying on LLM `store_document` tool-calling
- [x] Direct file processing: filter detects files in `inlet()` → sends to `/ingest/file` via HTTP → injects results into message
- [x] File detection: `_extract_files()` reads `body["files"][0]["file"]["path"]` (Open WebUI's nested file structure)
- [x] `_process_file_via_api()`: reads file from Docker path, sends as multipart upload to RAG API
- [x] `_format_result()`: formats API response with file type, chunks, facts, entities for LLM context
- [x] Debug mode valve: POSTs full request body to `/debug/filter-inlet` for troubleshooting
- [x] Anti-self-confirmation rule: "لا تسأل المستخدم هل تريد أضيف — أرسل الطلب مباشرة لأداة chat"
- [x] Anti-fake-STATUS rule: "لا تولّد STATUS: من عندك" (LLM was generating fake STATUS prefixes)
- [x] **Open WebUI Tools v2.0** (`openwebui_tools.py`): Removed `store_document` tool (now handled by filter). 20 tools total
- [x] **PDF vision fallback** (`files.py`): when pymupdf4llm extracts < 200 chars (scanned/image-heavy PDFs), converts pages to 200 DPI images → Qwen3-VL vision analysis (max 5 pages)
- [x] `_pdf_to_vision()` method: pymupdf render → base64 PNG → `llm.analyze_image()` → combines text from all pages
- [x] **Vision prompt improvement** (`vision.py`): `official_document` prompt now asks for `text_content`, `reference_numbers` (booking, reference_id, plate, id_number), `dates` with time
- [x] **Extract prompt rewrite** (`extract.py`): cleaner structure, explicit recurring reminder instructions (date = NEXT future occurrence), reference number extraction, 2 new few-shot examples
- [x] **Item quantity fix** (`graph.py`): `upsert_item` defaults to SET quantity on match (not ADD) via `quantity_mode` parameter. Prevents double-counting when image pipeline + post-processing both upsert same item
- [x] `FileUploadResponse` schema: added `entities: list[dict]` field
- [x] Config: added `chunk_max_tokens` (3000), `chunk_overlap_tokens` (150)
- [x] Debug endpoint: `POST /debug/filter-inlet` — dumps full body to `data/debug_filter_body.json`

### Phase 11 — Testing Results (all passed)
- [x] Backup: create (67KB graph, 2.4MB vector, 120KB redis), list, restore (183 nodes, 10 edges, 173 points, 107 keys)
- [x] NER: Log showed "NER hints: Detected entities: PERS: محمد; Location: الرياض"
- [x] Summarization: Summary returned Arabic text about conversation content
- [x] Streaming: NDJSON with meta, token chunks, done — all working
- [x] Graph Viz: schema (287 nodes, 74 edges), stats, export, PNG image generation verified
- [x] Regression: regular chat + proactive endpoints still work

---

## Future Ideas
- [ ] Import from external sources (Notion, Obsidian)
- [ ] WebSocket real-time updates
- [ ] User authentication (multi-user support)
- [ ] Gantt-style timeline view for projects
- [ ] Spaced repetition reminders for knowledge review
