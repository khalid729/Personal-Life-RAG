# API Reference

Base URL: `http://localhost:8500`

## Chat

### POST /chat/
Main conversational endpoint. Handles Arabic/English queries with agentic RAG.

**Request:**
```json
{
  "message": "رتب لي يومي",
  "session_id": "default"
}
```

**Response:**
```json
{
  "reply": "...",
  "sources": ["graph", "vector"],
  "route": "graph_daily_plan",
  "agentic_trace": [...],
  "pending_confirmation": false
}
```

Notes:
- If `pending_confirmation: true`, the next message should be yes/no/number
- `agentic_trace` shows the pipeline steps (route, act, reflect, retry)
- `sources` indicates where the context came from

---

## Ingestion

### POST /ingest/text
Ingest text into both vector store and knowledge graph.

**Request:**
```json
{
  "text": "محمد صديقي يشتغل في STC",
  "source_type": "note",
  "tags": ["friends"],
  "topic": "relationships"
}
```

**Response:**
```json
{
  "status": "ok",
  "chunks_stored": 1,
  "facts_extracted": 2,
  "entities": [
    {"type": "Person", "name": "محمد", "properties": {"company": "STC"}},
    {"type": "Company", "name": "STC"}
  ]
}
```

Notes:
- `entities` contains a list of extracted entities with their types and properties (added in `IngestResponse` schema)
- Used by the Open WebUI `store_document` tool to show detailed extraction results to the user

### POST /ingest/file
Upload and process a file (image/PDF/audio).

**Request:** `multipart/form-data` with `file` field

**Response:**
```json
{
  "status": "ok",
  "filename": "invoice.jpg",
  "file_type": "invoice",
  "file_hash": "abc123...",
  "analysis": {...},
  "chunks_stored": 1,
  "facts_extracted": 3,
  "processing_steps": ["classify", "analyze", "embed"],
  "auto_expense": {"amount": 150, "vendor": "Starbucks", "category": "food"}
}
```

---

## Search

### POST /search/
Direct search without generating a response.

**Request:**
```json
{
  "query": "IoT projects",
  "source": "auto",
  "limit": 5
}
```
`source`: `"auto"`, `"vector"`, or `"graph"`

**Response:**
```json
{
  "results": [
    {"text": "...", "score": 0.85, "source": "vector", "metadata": {...}}
  ],
  "source_used": "hybrid"
}
```

---

## Financial

### GET /financial/report
Monthly spending report with category breakdown.

**Parameters:** `month` (int), `year` (int), `compare` (bool)

**Response:**
```json
{
  "month": 2, "year": 2026,
  "total": 5400.0, "currency": "SAR",
  "by_category": [
    {"category": "food", "total": 2100, "count": 15, "percentage": 38.9}
  ],
  "comparison": null
}
```

### GET /financial/debts
All open/partial debts with net position.

**Response:**
```json
{
  "total_i_owe": 1100.0,
  "total_owed_to_me": 9400.0,
  "net_position": 8300.0,
  "debts": [
    {"person": "Mohammed", "amount": 1100, "direction": "i_owe", "status": "open", ...}
  ]
}
```

### POST /financial/debts/payment
Record a debt payment.

**Request:**
```json
{
  "person": "Mohammed",
  "amount": 500,
  "direction": "i_owe"
}
```

### GET /financial/alerts
Spending alerts (categories > 40% above 3-month average).

---

## Reminders

### GET /reminders/
List reminders (overdue + upcoming).

**Parameters:** `status` (string), `include_overdue` (bool, default true)

### POST /reminders/action
Perform action on a reminder (done/snooze/cancel).

**Request:**
```json
{
  "title": "pay rent",
  "action": "done"
}
```

### POST /reminders/update
Update reminder properties (title, due_date, priority, description, recurrence).

**Request:**
```json
{
  "title": "pay rent",
  "new_title": "pay rent and utilities",
  "due_date": "2026-03-01",
  "priority": 5
}
```

**Response:**
```json
{
  "title": "pay rent and utilities",
  "status": "pending",
  "due_date": "2026-03-01"
}
```

### POST /reminders/delete
Delete reminder(s) by title, node ID, or status.

**Request:**
```json
{"title": "buy milk"}
```
or `{"node_id": 205}` or `{"status": "cancelled"}`

**Response:**
```json
{
  "deleted": ["buy milk"],
  "count": 1
}
```

### POST /reminders/delete-all
Delete all reminders, optionally filtered by status.

**Parameters:** `status` (string, optional)

**Response:**
```json
{
  "deleted_count": 10,
  "titles": ["pay rent", "buy milk", "..."]
}
```

### POST /reminders/merge-duplicates
Find and merge duplicate reminders. Keeps one per unique title (best status, earliest due_date, lowest ID).

**Response:**
```json
{
  "merged_groups": [
    {"kept": "pay rent", "kept_id": 59, "removed_count": 3, "removed_ids": [76, 105, 202]}
  ],
  "total_removed": 3
}
```

---

## Projects

### GET /projects/
List all projects with task progress.

**Parameters:** `status` (string, optional) - filter by status (e.g. "active", "paused")

**Response:**
```json
{
  "projects": "Projects:\n  - Smart Home [active] [priority:3]\n  - Farm automation..."
}
```

### POST /projects/update
Create or update a project.

**Request:**
```json
{
  "name": "Smart Home",
  "status": "active",
  "description": "Home automation with IoT",
  "priority": 3
}
```

---

## Tasks

### GET /tasks/
List tasks with project links.

**Parameters:** `status` (string, optional) - filter by status (e.g. "todo", "in_progress", "done")

**Response:**
```json
{
  "tasks": "Tasks:\n  - Analyze expenses [todo]\n  - Set up reminders [todo]"
}
```

---

## Knowledge

### GET /knowledge/
Search knowledge entries.

**Parameters:** `topic` (string, optional) - filter by topic keyword

**Response:**
```json
{
  "knowledge": "Knowledge:\n  - ESP32 IoT Setup [hardware]\n    How to connect sensors..."
}
```

---

## Inventory

### GET /inventory/
List all inventory items, with optional search and category filter.

**Parameters:** `search` (string, optional), `category` (string, optional)

**Response:**
```json
{
  "items": "Items:\n  - USB-C cable (5 حبة) [إلكترونيات] — السطح > الرف الثاني\n  ..."
}
```

### GET /inventory/summary
Inventory statistics (total items, by category, by location).

**Response:**
```json
{
  "total_items": 42,
  "total_quantity": 156,
  "by_category": [{"category": "إلكترونيات", "count": 15, "quantity": 48}],
  "by_location": [{"location": "السطح > الرف الثاني", "count": 8}]
}
```

### POST /inventory/item
Create or update an inventory item.

**Request:**
```json
{
  "name": "USB-C cable",
  "quantity": 5,
  "location": "السطح > الرف الثاني",
  "category": "cables",
  "condition": "new",
  "brand": "Anker",
  "description": "2m USB-C to USB-C cable"
}
```
Note: Categories are auto-normalized (e.g. "cables" → "إلكترونيات").

### GET /inventory/by-file/{file_hash}
Find inventory item linked to a file by SHA256 hash.

**Response:**
```json
{
  "name": "USB-C cable",
  "quantity": 5,
  "location": "السطح > الرف الثاني"
}
```

### PUT /inventory/item/{name}/location
Update an item's storage location.

**Request:**
```json
{"location": "المكتب > الدرج الأول"}
```

### PUT /inventory/item/{name}/quantity
Update an item's quantity.

**Request:**
```json
{"quantity": 3}
```

### GET /inventory/by-barcode/{barcode}
Find inventory item by barcode/QR code value.

**Response (200):**
```json
{
  "name": "USB-C cable",
  "quantity": 5,
  "category": "إلكترونيات",
  "barcode_type": "EAN13",
  "location": "السطح > الرف الثاني"
}
```
Returns 404 if no item with that barcode.

### GET /inventory/report
Comprehensive inventory report with 7 sub-queries.

**Response:**
```json
{
  "total_items": 26,
  "total_quantity": 95,
  "by_category": [{"category": "إلكترونيات", "items": 10, "quantity": 35}],
  "by_location": [{"location": "السطح > الرف الثاني", "items": 8, "quantity": 20}],
  "by_condition": [{"condition": "new", "count": 15}],
  "without_location": 3,
  "unused_count": 19,
  "top_by_quantity": [{"name": "USB-C cable", "quantity": 10, "category": "إلكترونيات"}]
}
```

### GET /inventory/unused
Items not used/mentioned for N days.

**Parameters:** `days` (int, default 90)

**Response:**
```json
{
  "items": [
    {"name": "USB-C cable", "quantity": 5, "category": "إلكترونيات", "last_used_at": null, "location": "السطح"}
  ],
  "threshold_days": 90
}
```

### GET /inventory/duplicates
Detect potential duplicate items.

**Parameters:** `method` (string: `"name"` or `"vector"`, default `"name"`)

**Response:**
```json
{
  "duplicates": [
    {
      "item_a": {"name": "USB cable", "quantity": 3, "location": "السطح"},
      "item_b": {"name": "USB-C cable", "quantity": 5, "location": "المكتب"}
    }
  ]
}
```

### POST /inventory/search-similar
Search for similar inventory items by text description (vector similarity).

**Request:**
```json
{"description": "USB cable for charging"}
```

**Response:**
```json
{
  "results": [
    {"text": "USB-C cable - Anker 2m...", "score": 0.72, "metadata": {...}}
  ]
}
```

---

## Proactive System

Endpoints called by the scheduled jobs in the Telegram bot. Used for morning summaries, noon check-ins, evening summaries, and smart alerts.

### GET /proactive/morning-summary
Daily plan + spending alerts for morning notification.

**Response:**
```json
{
  "daily_plan": "...",
  "spending_alerts": "..."
}
```

### GET /proactive/noon-checkin
Overdue reminders for noon check-in.

**Response:**
```json
{
  "overdue_reminders": [
    {"title": "pay rent", "due_date": "2026-02-10T00:00:00", "reminder_type": "financial", "priority": "high", "description": "..."}
  ]
}
```

### GET /proactive/evening-summary
Tasks/reminders completed today + tomorrow's reminders.

**Response:**
```json
{
  "completed_today": ["pay rent", "buy groceries"],
  "tomorrow_reminders": [
    {"title": "meeting", "due_date": "2026-02-12T09:00:00", "reminder_type": "one_time", "priority": "medium"}
  ]
}
```

### GET /proactive/due-reminders
All reminders that are past due (for reminder check job).

**Response:**
```json
{
  "due_reminders": [
    {"title": "...", "due_date": "...", "reminder_type": "...", "priority": "...", "description": "...", "recurrence": "monthly"}
  ]
}
```

### POST /proactive/advance-reminder
Advance a recurring reminder to its next due date.

**Request:**
```json
{"title": "renew template", "recurrence": "monthly"}
```

### GET /proactive/stalled-projects
Active projects with no task updates in N days.

**Parameters:** `days` (int, default 14)

**Response:**
```json
{
  "stalled_projects": [
    {"name": "...", "status": "active", "last_activity": "...", "task_count": 3}
  ],
  "days_threshold": 14
}
```

### GET /proactive/old-debts
Debts I owe that are older than N days.

**Parameters:** `days` (int, default 30)

**Response:**
```json
{
  "old_debts": [
    {"person": "Mohammed", "amount": 500, "reason": "lunch", "created_at": "...", "status": "open"}
  ],
  "days_threshold": 30
}
```

---

## Productivity

### POST /productivity/sprints/
Create a new sprint.

**Request:**
```json
{
  "name": "Sprint 1",
  "start_date": "2026-02-10",
  "end_date": "2026-02-24",
  "goal": "Complete authentication module",
  "project": "Smart Home"
}
```

### GET /productivity/sprints/
List sprints.

**Parameters:** `status` (string, optional) — filter by status (active, completed)

### GET /productivity/sprints/{name}/burndown
Sprint burndown data (ideal vs actual remaining, progress %).

### POST /productivity/sprints/{name}/complete
Mark a sprint as completed.

### GET /productivity/sprints/velocity
Sprint velocity (avg tasks/week across completed sprints).

**Parameters:** `project` (string, optional) — filter by project name

### POST /productivity/sprints/{sprint}/tasks/{task}
Assign a task to a sprint.

### POST /productivity/focus/start
Start a focus (pomodoro) session.

**Request:**
```json
{
  "duration_minutes": 25,
  "task": "Design database schema"
}
```

### POST /productivity/focus/complete
Complete the current focus session.

**Request:**
```json
{"completed": true}
```

### GET /productivity/focus/stats
Focus session statistics (total sessions, total minutes, avg duration, completion rate).

### POST /productivity/timeblock/suggest
Suggest time blocks for a date based on task energy levels.

**Request:**
```json
{
  "date": "2026-02-11",
  "energy_override": null
}
```

### POST /productivity/timeblock/apply
Apply suggested time blocks to tasks.

---

## Backup

### POST /backup/create
Create a full backup of graph, vector, and Redis data.

**Response:**
```json
{
  "timestamp": "20260211_150000",
  "path": "data/backups/20260211_150000",
  "sizes": {"graph": 67000, "vector": 2400000, "redis": 120000},
  "old_backups_removed": 0
}
```

### GET /backup/list
List available backups.

**Response:**
```json
{
  "backups": [
    {"timestamp": "20260211_150000", "path": "...", "sizes": {...}}
  ]
}
```

### POST /backup/restore/{timestamp}
Restore from a specific backup.

**Response:**
```json
{
  "status": "restored",
  "timestamp": "20260211_150000",
  "graph": {"nodes_restored": 183, "edges_restored": 10},
  "vector": {"points_restored": 173},
  "redis": {"keys_restored": 107}
}
```

---

## Chat (Streaming + Summary)

### POST /chat/stream
Streaming chat response via NDJSON.

**Request:** Same as POST /chat/

**Response:** `application/x-ndjson` stream:
```
{"type":"meta","route":"graph_task","sources":["graph"],"agentic_trace":[...]}
{"type":"token","content":"مهام"}
{"type":"token","content":"ك "}
{"type":"token","content":"اليوم:"}
...
{"type":"done"}
```

### GET /chat/summary
Get or generate conversation summary.

**Parameters:** `session_id` (string, required)

**Response:**
```json
{
  "summary": "ملخص المحادثة: ...",
  "message_count": 15
}
```

---

## Graph Visualization

### GET /graph/export
Export subgraph as JSON (nodes + edges).

**Parameters:**
- `entity_type` (string, optional) — filter by node label (e.g. "Person")
- `center` (string, optional) — ego-graph center node name
- `hops` (int, default 2) — ego-graph traversal depth (1-5)
- `limit` (int, default 500) — max nodes (1-5000)

**Response:**
```json
{
  "nodes": [{"id": 1, "label": "محمد", "type": "Person", "properties": {...}}],
  "edges": [{"source": 1, "target": 2, "type": "WORKS_AT", "properties": {}}]
}
```

### GET /graph/schema
Node labels, relationship types, and counts.

**Response:**
```json
{
  "node_labels": {"Person": 5, "Task": 20, "Project": 3},
  "relationship_types": {"BELONGS_TO": 15, "INVOLVES": 8},
  "total_nodes": 287,
  "total_edges": 74
}
```

### GET /graph/stats
Total nodes, edges, and by-type counts.

**Response:**
```json
{
  "total_nodes": 287,
  "total_edges": 74,
  "by_type": {"Person": 5, "Task": 20, "Expense": 45}
}
```

### POST /graph/image
Generate PNG image of the graph.

**Request:**
```json
{
  "entity_type": "Person",
  "center": "محمد",
  "hops": 2,
  "width": 1200,
  "height": 800,
  "limit": 500
}
```

**Response:** PNG image (`image/png`)

---

## Health

### GET /health
```json
{"status": "ok"}
```

---

## Telegram Bot Commands

The Telegram bot runs as a separate process and calls the RAG API. Auth: only responds to the configured `TG_CHAT_ID`.

| Command | Description | API Call |
|---------|-------------|----------|
| `/start` | Welcome message with command list | — |
| `/plan` | Today's daily plan | `POST /chat/` ("رتب لي يومي") |
| `/debts` | Debt summary (owe/owed) | `GET /financial/debts` |
| `/reminders` | Active reminders | `GET /reminders/` |
| `/projects` | Projects overview | `GET /projects/` |
| `/tasks` | Tasks list | `GET /tasks/` |
| `/report` | Monthly financial report | `GET /financial/report` |
| `/inventory` | Inventory items list | `GET /inventory/` |
| `/inventory report` | Inventory report (stats) | `GET /inventory/report` |
| `/focus` | Focus session (start/done/stats) | `POST /productivity/focus/*` |
| `/sprint` | Sprint list with progress bars | `GET /productivity/sprints/` |
| `/backup` | Create backup / list backups | `POST /backup/create`, `GET /backup/list` |
| `/graph` | Graph schema / type image / ego-graph | `GET /graph/schema`, `POST /graph/image` |

### Message Types
- **Text** → `POST /chat/stream` → NDJSON streaming → edits placeholder message with tokens
- **Voice** → download .ogg → `POST /ingest/file` → transcription + processing
- **Photo** → download → `POST /ingest/file` → classification + analysis
- **Document** → download → `POST /ingest/file` → processing
- **Confirmation** → inline keyboard (✅ نعم / ❌ لا) when `pending_confirmation=true`

---

## MCP Server Tools

The MCP server runs on port 8600 (SSE transport) and exposes 24 tools:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `chat` | `message`, `session_id` | Conversational interface |
| `search` | `query`, `source`, `limit` | Knowledge search (vector/graph/auto) |
| `create_reminder` | `text` | Create reminder via natural language |
| `record_expense` | `text` | Record expense via natural language |
| `get_financial_report` | `month`, `year` | Monthly spending report |
| `get_debts` | — | Debt summary |
| `get_reminders` | — | Active reminders |
| `delete_reminder` | `title` | Delete reminder by title |
| `update_reminder` | `title`, `new_title`, `due_date`, `priority` | Update reminder properties |
| `delete_all_reminders` | — | Delete all reminders |
| `merge_duplicate_reminders` | — | Find and merge duplicate reminders |
| `get_projects` | `status` | Projects overview |
| `get_tasks` | `status` | Tasks list |
| `get_knowledge` | `topic` | Knowledge entries |
| `daily_plan` | — | Today's aggregated plan |
| `ingest_text` | `text`, `source_type` | Store text in knowledge base |
| `get_inventory` | `search`, `category` | Inventory items list |
| `get_inventory_report` | — | Comprehensive inventory report |
| `get_sprints` | `status` | Sprint list with burndown data |
| `get_focus_stats` | — | Focus session statistics |
| `create_backup` | — | Create full system backup |
| `list_backups` | — | List available backups |
| `get_graph_schema` | — | Graph node labels + relationship types |
| `get_graph_stats` | — | Graph node/edge counts by type |
