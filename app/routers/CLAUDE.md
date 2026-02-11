# Routers

15 REST routers, all use `request.app.state.<service>` to access services.

## Endpoint Map

| Router | Prefix | Key Endpoints |
|--------|--------|---------------|
| chat | `/chat` | POST / (main chat), POST /stream (NDJSON), POST /summary |
| ingest | `/ingest` | POST /text, POST /file (upload) |
| files | `/ingest` | POST /file (upload), GET /file/{hash} (download) |
| search | `/search` | POST / (vector/graph) |
| financial | `/financial` | GET /report, /debts, /alerts, POST /debts/payment |
| reminders | `/reminders` | GET /, POST /action, /update, /delete, /delete-all, /merge-duplicates |
| tasks | `/tasks` | GET / |
| projects | `/projects` | GET /, POST /update |
| knowledge | `/knowledge` | GET / |
| inventory | `/inventory` | GET /, POST /item, PUT /item/{name}/location, GET /unused, /report, /duplicates, /by-barcode/{barcode}, POST /search-similar |
| productivity | `/productivity` | Sprints CRUD, focus sessions, time-blocking |
| proactive | `/proactive` | Morning summary, noon check-in, evening review, smart alerts |
| backup | `/backup` | POST /create, GET /list, POST /restore/{timestamp} |
| graph_viz | `/graph` | GET /export, /schema, /stats, POST /image (PNG) |

## Pattern

```python
router = APIRouter(prefix="/prefix", tags=["tag"])

@router.post("/endpoint")
async def endpoint(request: Request):
    service = request.app.state.retrieval
    result = await service.method()
    return result
```

## Chat Flow (POST /chat)

1. `retrieval.retrieve_and_respond(message, session_id)`
2. Returns `ChatResponse(reply, sources, route, agentic_trace, pending_confirmation)`
3. BackgroundTasks: memory update + fact extraction + embeddings

## Streaming (POST /chat/stream)

NDJSON format:
```
{"type":"meta", ...}
{"type":"token", "content":"..."}
{"type":"done"}
```

## Reminders — All POST for Open WebUI tool compatibility

- POST /update (ReminderUpdateRequest)
- POST /delete (ReminderDeleteRequest)
- POST /delete-all
- POST /merge-duplicates

## Debug

- POST /debug/filter-inlet → dumps body to data/debug_filter_body.json

## Smart Router Keywords (20 patterns, specificity order)

1. سدد/رجع/paid back → graph_debt_payment
2. ديون/يطلبني → graph_debt_summary
3. ملخص/كم صرفت → graph_financial_report
4. صرفت/دفعت → graph_financial
5. خلصت/snooze + reminder → graph_reminder_action
6. ذكرني/موعد → graph_reminder
7. رتب يومي → graph_daily_plan
8. وش أعرف → graph_knowledge
9. سبرنت/burndown → graph_sprint
10. focus/تركيز → graph_focus_stats
11. رتب.*وقت/time.?block → graph_timeblock
12. إنتاجية → graph_productivity_report
13. Project/Person/Task keywords → graph_project/person/task
14-19. Inventory (duplicates/report/move/usage/unused/query)
20. Fallback → LLM classify
