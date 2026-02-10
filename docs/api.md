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
  "facts_extracted": 2
}
```

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

## Health

### GET /health
```json
{"status": "ok"}
```
