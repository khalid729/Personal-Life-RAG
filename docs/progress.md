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
- [x] REST endpoints: /financial/report, /debts, /debts/payment, /alerts, /reminders/, /reminders/action

### Phase 4a — Smarter Conversations
- [x] Confirmation flow for side-effect routes (financial, debt_payment, reminder)
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
- [x] MCP server (FastMCP, SSE on port 8600, 12 tools)
- [x] MCP tools: chat, search, create_reminder, record_expense, financial report, debts, reminders, projects, tasks, knowledge, daily plan, ingest text
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

---

## Remaining Phases

### Phase 8 — Smart Knowledge + Entity Resolution
- [ ] Entity resolution / dedup (merge "Mohammed" / "Mohamed" / "محمد" via vector similarity)
- [ ] Auto-tag knowledge entries by category
- [ ] Smart Tags with vector dedup (tag normalization before creation)
- [ ] Multi-hop graph traversal in retrieval (beyond 2-hop)
- [ ] Community detection (auto-cluster related entities)
- [ ] Graph-based ranking (PageRank on entities for importance scoring)

### Phase 9 — Advanced Inventory
- [ ] QR/Barcode scanning → contents of box/container
- [ ] Last-use tracking ("كم غرض عندي ما استخدمته من سنة؟")
- [ ] Comprehensive inventory report (by category, location, value)
- [ ] Duplicate detection across locations (similar items in different places)

### Phase 10 — Productivity Enhancements
- [ ] Time-blocking suggestions based on task priorities (ADHD Mode)
- [ ] Energy-level awareness (morning vs evening tasks)
- [ ] Pomodoro-style breakdowns for large tasks
- [ ] Auto-link tasks to projects via LLM context
- [ ] Sprint/milestone tracking
- [ ] Progress percentage calculation

### Phase 11 — Infrastructure + Quality
- [ ] Streaming responses (SSE from vLLM → FastAPI → client)
- [ ] Conversation summarization for long sessions
- [ ] Backup/export (graph + vector snapshots)
- [ ] Arabic NER improvement (custom patterns for Saudi names/places)
- [ ] Knowledge graph visualization
- [ ] Import from external sources (Notion, Obsidian)

### Future Ideas
- [ ] WebSocket real-time updates
- [ ] User authentication (multi-user support)
- [ ] Gantt-style timeline view for projects
- [ ] Spaced repetition reminders for knowledge review
