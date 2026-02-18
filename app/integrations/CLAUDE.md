# Integrations

5 external interfaces → FastAPI :8500. **All unified on `/chat/v2` (tool-calling).**

## Telegram Bot (telegram_bot.py)

- aiogram 3.x + APScheduler
- **Text**: streams via `/chat/v2/stream`, fallback to `/chat/v2` non-streaming
- **Voice/Photos/Files**: processed via `/ingest/file`, then result injected into chat
- **Image analysis summary**: still uses `/chat/` (legacy, needs vision model)
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
- Handles files via `/ingest/file` (base64, Docker paths, multimodal)
- No STATUS logic needed — streams RAG API response directly
- Select "Personal RAG" model in Open WebUI to use; regular model uses Filter + Tools

## Open WebUI Filter (openwebui_filter.py)

- Inlet: detects files → `/ingest/file` → injects results
- Prepends date/time + Arabic rules to system prompt
- Anti-lying: STATUS prefix (`ACTION_EXECUTED | CONVERSATION`)
- Key rules: no fake "تم", no invented names, no asking "هل تريد أن أضيف?"

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
