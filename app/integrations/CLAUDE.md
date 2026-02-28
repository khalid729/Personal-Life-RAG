# Integrations

5 external interfaces → FastAPI :8500. **All unified on `/chat/v2` (tool-calling).**

## Telegram Bot (telegram_bot.py)

- aiogram 3.x + APScheduler
- **Text**: streams via `/chat/v2/stream`, fallback to `/chat/v2` non-streaming
- **Reply context**: when user replies to a message, quoted text (first 200 chars) is prepended as `[رد على: "..."]` — enables updating a reminder by quoting its notification and replying "أجله لبكرة"
- **Voice/Photos/Files**: processed via `/ingest/file`, then result injected into chat
- **Image analysis summary**: uses `/chat/v2`
- **No confirmation flow** — tools execute directly
- Commands: `/help`, `/chat`, `/finance`, `/reminders`, `/projects`, `/tasks`, `/inventory`, `/focus`, `/sprint`, `/backup`, `/graph`
- Scheduled: morning (7AM), noon (1PM), evening (9PM), reminders (30min), smart alerts (6h)
- **Persistent nag loop**: `job_check_reminders()` — after mark-notified, persistent reminders call `/proactive/reschedule-persistent` to auto-reschedule for next nag cycle

## Open WebUI Tools (openwebui_tools.py)

- 21 sync tools via `http://host.docker.internal:8500`
- chat → `/chat/v2`, other tools → direct REST endpoints
- **STATUS detection**: checks `tool_calls` list for successful writes → `ACTION_EXECUTED`
- No more `PENDING_CONFIRMATION` — tools execute directly

## Open WebUI Pipe (openwebui_pipe.py)

- **Direct streaming** to `/chat/v2/stream` — bypasses wrapper LLM entirely
- 2 LLM calls (tool selection + response) via tool-calling
- **Docker path builder**: `_get_owui_file_path()` builds path from OWUI convention `/app/backend/data/uploads/{id}_{filename}` (OWUI doesn't store `path` in file meta)
- **Ingestion cache**: `_ingested_files` set tracks processed file IDs — skips re-ingestion on subsequent messages
- **RAG context stripping**: `_strip_owui_rag_context()` removes OWUI's injected `### Task/Context/Query` wrapper — stripped BEFORE file processing to prevent RAG garbage in `/ingest/file` context param
- **Stream with files**: `_stream_with_files()` yields "جاري معالجة الملف..." immediately, then streams chat — prevents OWUI timeout during long ingestion
- All files → `/ingest/file` (raw bytes from Docker path, includes text types like .md/.txt)
- No STATUS logic needed — streams RAG API response directly
- Select "Personal RAG" model in Open WebUI to use

## Open WebUI Filter (openwebui_filter.py)

- **v2.1**: File-processing-only filter (standalone, without Pipe)
- Inlet: detects files (base64, Docker path, body-level) → `/ingest/file` → injects results into message
- Supports text MIME types: .md, .txt, .csv, .log, .json, .xml, .yaml, .py, .js, .ts
- No system prompt injection — lightweight file handler only
- **Note**: Filter can't see files when paired with Pipe (`__files__` only passed to Pipe, not Filter). Use Pipe's built-in file processing instead.

## MCP Server — Open WebUI (:8600)

- SSE-based, prepends date context to every response
- Uses `/chat/v2` — checks `tool_calls` for successful writes → `ACTION_EXECUTED`

## MCP Server — Claude Desktop (mcp_server_desktop.py)

- **stdio transport** — Claude Desktop spawns process directly
- 15 direct REST tools — no double-LLM, no STATUS detection
- Claude handles Arabic, date parsing, category inference natively
- `create_reminder` / `record_expense` use `/chat/v2` (tool-calling endpoint)
- `create_reminder` has `prayer` param — maps to Arabic prayer name in message so `/chat/v2` LLM resolves the time
- All other tools call REST endpoints directly (GET/POST)
- Config: `~/.config/Claude/claude_desktop_config.json`
