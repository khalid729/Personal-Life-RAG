# Routers

15 REST routers, all use `request.app.state.<service>`.

## Endpoints

| Router | Prefix | Key Endpoints |
|--------|--------|---------------|
| chat | `/chat` | POST / , POST /stream (NDJSON), POST /summary |
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

## Chat Flow

1. `retrieval.retrieve_and_respond(message, session_id)`
2. Returns `ChatResponse(reply, sources, route, agentic_trace, pending_confirmation)`
3. BackgroundTasks: memory + extraction + embeddings

## Streaming — NDJSON

```
{"type":"meta", ...} → {"type":"token", "content":"..."} → {"type":"done"}
```

## Smart Router (20 patterns, specificity order)

1. سدد/paid back → debt_payment  2. ديون/يطلبني → debt_summary
3. ملخص/كم صرفت → financial_report  4. صرفت/دفعت → financial
5. خلصت/snooze → reminder_action  6. ذكرني/موعد → reminder
7. رتب يومي → daily_plan  8. وش أعرف → knowledge
9-12. Sprint/focus/timeblock/productivity  13. Project/Person/Task
14-19. Inventory patterns  20. Fallback → LLM classify
