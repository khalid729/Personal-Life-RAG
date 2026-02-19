# Integrations

5 external interfaces → FastAPI :8500. **All unified on `/chat/v2` (tool-calling).**

## Telegram Bot (telegram_bot.py)

- aiogram 3.x + APScheduler
- **Text**: streams via `/chat/v2/stream`, fallback to `/chat/v2` non-streaming
- **Voice/Photos/Files**: processed via `/ingest/file`, then result injected into chat
- **Image analysis summary**: uses `/chat/v2`
- **No confirmation flow** — tools execute directly
- Commands: `/help`, `/chat`, `/finance`, `/reminders`, `/projects`, `/tasks`, `/inventory`, `/focus`, `/sprint`, `/backup`, `/graph`
- Scheduled: morning (7AM), noon (1PM), evening (9PM), reminders (30min), smart alerts (6h)

## Open WebUI Tools (openwebui_tools.py)

- 21 sync tools via `http://host.docker.internal:8500`
- chat → `/chat/v2`, other tools → direct REST endpoints
- **STATUS detection**: checks `tool_calls` list for successful writes → `ACTION_EXECUTED`
- No more `PENDING_CONFIRMATION` — tools execute directly

## Open WebUI Pipe (openwebui_pipe.py)

- **Direct streaming** to `/chat/v2/stream` — bypasses wrapper LLM entirely
- 2 LLM calls (tool selection + response) via tool-calling
- **Full file extraction**: `_fetch_owui_file_content()` via direct `open_webui.models.files.Files` import
- **Ingestion cache**: `_ingested_files` set tracks processed file IDs — skips re-ingestion on subsequent messages
- **RAG context stripping**: `_strip_owui_rag_context()` removes OWUI's injected `### Task/Context/Query` wrapper
- All files → `/ingest/file` (raw bytes, includes text types like .md/.txt)
- No STATUS logic needed — streams RAG API response directly
- **Pairing with Filter**: set `auto_process_files = False` when Filter handles files
- Select "Personal RAG" model in Open WebUI to use

## Open WebUI Filter (openwebui_filter.py)

- **v2.1**: File-processing-only filter — pairs with Pipe for chat
- Inlet: detects files (base64, Docker path, body-level) → `/ingest/file` → injects results into message
- Supports text MIME types: .md, .txt, .csv, .log, .json, .xml, .yaml, .py, .js, .ts
- No system prompt injection (Pipe + `/chat/v2` handles date/rules)
- No Strategy 2 fallback (removed `/ingest/text` path)
- Attach both Filter + Pipe to same model; set Pipe `auto_process_files = False`

## MCP Server — Open WebUI (:8600)

- SSE-based, prepends date context to every response
- Uses `/chat/v2` — checks `tool_calls` for successful writes → `ACTION_EXECUTED`

## MCP Server — Claude Desktop (mcp_server_desktop.py)

- **stdio transport** — Claude Desktop spawns process directly
- 15 direct REST tools — no double-LLM, no STATUS detection
- Claude handles Arabic, date parsing, category inference natively
- `create_reminder` / `record_expense` use `/chat/v2` (tool-calling endpoint)
- All other tools call REST endpoints directly (GET/POST)
- Config: `~/.config/Claude/claude_desktop_config.json`
