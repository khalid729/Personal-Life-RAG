# Routers

17 REST routers, all use `request.app.state.<service>`.

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
| proactive | `/proactive` | Morning/noon/evening summaries, smart alerts, reschedule-persistent |
| backup | `/backup` | POST /create, GET /list, POST /restore/{timestamp} |
| graph_viz | `/graph` | GET /export, /schema, /stats, POST /image |
| location | `/location` | POST /update (webhook), GET/POST/DELETE /places, GET /current |
| users | `/admin` | GET /users, POST /users, GET /users/by-telegram/{tg_id}, DELETE /users/{user_id} |

## Chat Flow (Tool-Calling)

1. `tool_calling.chat(message, session_id)` — LLM picks tools → code executes → LLM formats
2. Returns `ChatResponse(reply, sources, route, agentic_trace, tool_calls)`
3. Post-processing: memory + vector + auto-extraction (runs in background via `asyncio.create_task`)

## Streaming — NDJSON

```
{"type":"meta", ...} → {"type":"token", "content":"..."} → {"type":"done"}
```

## Location Router (Phase 24)

- `POST /location/update` — main webhook for HA zone events + OwnTracks transitions
  - Normalizes payload (HA `zone_name`+`event` vs OwnTracks `_type`+`desc`)
  - Updates current position in Redis
  - Checks all saved Places via geofence → returns entered/left lists
  - Auto-creates Place nodes for unknown HA zones (`source="ha_zone"`)
  - Queries location reminders matching place name or POI type (via reverse geocode)
  - Sends Telegram notification via per-user bot token (`_get_bot_token()`) + marks notified + re-arms persistent on zone leave
  - Cooldown prevents duplicate fires within `location_cooldown_minutes`
- `GET /location/places` — list saved places (optional `place_type` filter)
- `POST /location/places` — create/update place
- `DELETE /location/places/{name}` — delete place
- `GET /location/current` — current position + active zones from Redis

## Users Router (Phase 23)

- `GET /admin/users` — list all registered users
- `POST /admin/users` — register new user (generates API key, creates graph + collection)
- `GET /admin/users/by-telegram/{tg_id}` — resolve Telegram user to profile
- `DELETE /admin/users/{user_id}` — disable user (soft delete)
- Protected by `X-Admin-Key` header or localhost-only access

## Multi-Tenancy Middleware

- `AuthMiddleware` in `app/middleware/auth.py` — runs on every request (skips `/health`, `/docs`)
- When `multi_tenant_enabled=False` (default): sets context vars to existing settings (zero change)
- When enabled: reads `X-API-Key` → `UserRegistry.get_user_by_api_key()` → sets context vars
- Context vars (`_current_graph_name`, `_current_collection`, `_current_redis_prefix`, `_current_user_nickname`, `_current_user_gender`, `_current_anthropic_key`) are task-local, inherited by `asyncio.create_task`
- `request.state.user_ctx` available to all route handlers
