# Routers

15 REST routers, all use `request.app.state.<service>`.

## Endpoints

| Router | Prefix | Key Endpoints |
|--------|--------|---------------|
| chat | `/chat` | POST /v2 (tool-calling), POST /v2/stream (NDJSON), GET /summary |
| ingest | `/ingest` | POST /text, POST /file |
| files | `/ingest` | POST /file, POST /url, GET /file/{hash} |
| search | `/search` | POST / |
| financial | `/financial` | GET /report, /debts, /alerts, POST /debts/payment |
| reminders | `/reminders` | GET /, POST /action, /update, /delete, /delete-all, /merge-duplicates |
| tasks | `/tasks` | GET / |
| projects | `/projects` | GET /, POST /update |
| knowledge | `/knowledge` | GET / |
| inventory | `/inventory` | GET /, POST /item, PUT /item/{name}/location, GET /unused, /report, /duplicates |
| productivity | `/productivity` | Sprints CRUD, focus sessions, time-blocking |
| proactive | `/proactive` | Morning/noon/evening summaries, smart alerts |
| backup | `/backup` | POST /create, GET /list, POST /restore/{timestamp} |
| graph_viz | `/graph` | GET /export, /schema, /stats, POST /image |

## Chat Flow (Tool-Calling)

1. `tool_calling.chat(message, session_id)` — LLM picks tools → code executes → LLM formats
2. Returns `ChatResponse(reply, sources, route, agentic_trace, tool_calls)`
3. Post-processing: memory + vector + auto-extraction (runs in background via `asyncio.create_task`)

## Streaming — NDJSON

```
{"type":"meta", ...} → {"type":"token", "content":"..."} → {"type":"done"}
```
