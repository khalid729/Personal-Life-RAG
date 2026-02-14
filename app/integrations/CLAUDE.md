# Integrations

3 external interfaces → FastAPI :8500.

## Telegram Bot (telegram_bot.py)

- aiogram 3.x + APScheduler
- Handles: text (streaming), voice (WhisperX), photos (vision), files
- Commands: `/help`, `/chat`, `/finance`, `/reminders`, `/projects`, `/tasks`, `/inventory`, `/focus`, `/sprint`, `/backup`, `/graph`
- Scheduled: morning (7AM), noon (1PM), evening (9PM), reminders (30min), smart alerts (6h)

## Open WebUI Tools (openwebui_tools.py)

- 21 sync tools via `http://host.docker.internal:8500`
- chat, search, financial, debts, reminders, projects, tasks, knowledge, inventory, sprints, focus, backup, graph, ingest_url
- **STATUS detection**: checks `agentic_trace` for `extract.upserted > 0` → `ACTION_EXECUTED` (trace-based, not route-based)

## Open WebUI Filter (openwebui_filter.py)

- Inlet: detects files → `/ingest/file` → injects results
- Prepends date/time + Arabic rules to system prompt
- Anti-lying: STATUS prefix (`ACTION_EXECUTED | PENDING_CONFIRMATION | CONVERSATION`)
- Key rules: no fake "تم", no invented names, no asking "هل تريد أن أضيف?"

## MCP Server (:8600)

- SSE-based, prepends date context to every response
- Same trace-based STATUS detection as tools (`extract.upserted > 0` → `ACTION_EXECUTED`)
