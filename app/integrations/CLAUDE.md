# Integrations

3 external interfaces connecting to the FastAPI API on :8500.

## Telegram Bot (telegram_bot.py — 49KB, largest file)

- Framework: aiogram 3.x + APScheduler
- Handles: text (streaming NDJSON), voice (transcription), photos (vision), files (upload)
- Streaming: `chat_api_stream()` → edits placeholder message with tokens

### Commands
`/help`, `/chat`, `/finance`, `/reminders`, `/projects`, `/tasks`, `/inventory`, `/focus`, `/sprint`, `/backup`, `/graph`

### Subcommands
- `/inventory report` — full inventory report
- `/focus start|done|stats` — focus session management
- `/sprint` — list with progress bars
- `/backup create|list`
- `/graph schema|type|ego` — schema text, type image (PNG), ego-graph image

### Scheduled Jobs (5)
1. Morning summary (7 AM)
2. Noon check-in (1 PM)
3. Evening review (9 PM)
4. Reminder alerts (every 30 min)
5. Smart alerts (every 6 hours)

## Open WebUI Tools (openwebui_tools.py — 16KB)

v2.0, 20 tools. Runs inside Docker → calls `http://host.docker.internal:8500`.
All calls are **synchronous** (requests, not httpx) because Open WebUI tool runtime is sync.

### Tool List
chat, search, financial_report, get_debts, record_debt_payment, get_financial_alerts,
list_reminders, create_reminder, delete_reminder, update_reminder, delete_all_reminders, merge_duplicate_reminders,
list_projects, update_project, list_tasks, list_knowledge,
list_inventory, get_inventory_report, get_unused_items, get_duplicate_items,
list_sprints, create_sprint, get_focus_stats,
create_backup, list_backups, export_graph, graph_schema, graph_stats

## Open WebUI Filter (openwebui_filter.py — 24KB)

v2.0. Runs as inlet/outlet filter in Open WebUI pipeline.

### Inlet (pre-processing)
- Detects files in `body["files"][0]["file"]["path"]` (Docker path)
- Reads file directly → sends to `/ingest/file` API
- Injects results into message

### Outlet (post-processing)
- Injects date/time + strict Arabic instructions into system prompt
- Anti-lying: "ممنوع تقول 'تم' إلا إذا شفت STATUS: ACTION_EXECUTED"

### Anti-Lying Protocol
Every `chat` tool response is prefixed: `STATUS: ACTION_EXECUTED | PENDING_CONFIRMATION | CONVERSATION`

Filter rules:
- Rule 8: "لا تسأل المستخدم هل تريد أضيف — أرسل الطلب مباشرة لأداة chat"
- "لا تولّد STATUS: من عندك" (LLM was generating fake STATUS prefixes)

## MCP Server (port 8600)

SSE-based MCP server. `_current_date_context()` helper prepends date to every response.
