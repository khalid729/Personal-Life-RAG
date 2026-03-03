# Lovable Prompt: Personal Life RAG Admin Dashboard

## Context

This is a comprehensive prompt to paste into Lovable (AI app builder) to generate a full admin dashboard for the Personal Life RAG system. It covers all 17 pages: Dashboard, Chat, Reminders, Tasks, Projects, Financial, Inventory, Knowledge, Map & Places (Leaflet + Esri satellite), Productivity, Graph Explorer, Search, Ingest, Proactive, User Management, Backup, and Settings.

The prompt is self-contained with all API endpoints, data models, UI specifications, and component requirements. No code changes to the backend are needed.

---

## Lovable Prompt (copy everything below this line)

---

Build a complete admin dashboard for a Personal Life RAG (Retrieval-Augmented Generation) system. This is an Arabic-first personal knowledge management platform with agentic AI, a knowledge graph, financial tracking, reminders, location geofencing, inventory, productivity tools, and multi-user support. The dashboard connects to an existing FastAPI backend.

---

### GLOBAL CONFIGURATION

Create a config module (`src/config.ts`) with:
```ts
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
export const API_KEY = import.meta.env.VITE_API_KEY || "";
export const ADMIN_KEY = import.meta.env.VITE_ADMIN_KEY || "";
```

Every API call must include the header `X-API-Key` with the configured API key. Admin endpoints (`/admin/*`) must also include `X-Admin-Key`. Create a shared `apiClient` (using `fetch` or a small wrapper) that automatically injects these headers:
```
X-API-Key: <API_KEY>
X-Admin-Key: <ADMIN_KEY>  (only for /admin/* routes)
Content-Type: application/json
```

---

### GLOBAL UI / LAYOUT REQUIREMENTS

1. **RTL-first layout**: The entire app must use `dir="rtl"` on the root element. All text alignment, padding, margins, and flexbox directions must respect RTL. Use Tailwind's RTL plugin or manual `rtl:` utilities. Arabic is the primary language, but English labels/headers may appear alongside Arabic in some places (e.g., entity type badges, status badges).

2. **Dark mode**: Support both light and dark themes. Default to dark. Use a toggle in the top bar. Persist preference to localStorage. Use Tailwind dark mode classes (`dark:bg-gray-900`, etc.) or shadcn/ui themes.

3. **Responsive**: Must work on both desktop (1200px+) and mobile (320px). Use a collapsible sidebar on desktop that becomes a hamburger-menu drawer on mobile.

4. **Design system**: Use shadcn/ui components (Button, Card, Table, Dialog, Input, Select, Badge, Tabs, Toast, Sheet, DropdownMenu, Tooltip, Switch). Use Lucide icons. Use Recharts for all charts.

5. **Color palette for entity types** (used in graph visualization, badges, and cards):
   - Person: `#4A90D9` (blue)
   - Project: `#E8943A` (orange)
   - Task: `#5CB85C` (green)
   - Expense: `#D9534F` (red)
   - Debt: `#F0AD4E` (gold)
   - Reminder: `#9B59B6` (purple)
   - Company: `#3498DB` (sky blue)
   - Item: `#1ABC9C` (teal)
   - Knowledge: `#2ECC71` (emerald)
   - Topic: `#95A5A6` (gray)
   - Tag: `#BDC3C7` (light gray)
   - Sprint: `#E74C3C` (crimson)
   - Idea: `#F39C12` (amber)
   - FocusSession: `#8E44AD` (dark purple)
   - Place/Location: `#16A085` (dark teal)
   - File: `#607D8B` (blue-gray)

6. **Sidebar navigation** with sections:
   - **Main**: Dashboard (home), Chat
   - **Data**: Reminders, Tasks, Projects, Financial, Inventory, Knowledge
   - **Location**: Map & Places
   - **Productivity**: Sprints, Focus Sessions, Time Blocking
   - **System**: Graph Explorer, Search, Ingest, Proactive, Users (admin), Backup, Settings

   Each item has a Lucide icon. The active page is highlighted. The sidebar header shows the app name "RAG Dashboard" and the current user name.

7. **Toast notifications**: Show success/error toasts for all API operations using sonner or shadcn toast.

8. **Loading states**: Show skeleton/spinner for every data fetch. Show empty state illustrations when no data.

9. **Fonts**: Use "IBM Plex Sans Arabic" from Google Fonts as the primary font. Fallback to system Arabic fonts.

---

### PAGE 1: DASHBOARD (Home — `/`)

The main dashboard shows an at-a-glance overview of the entire system.

**Top row — 6 stat cards in a responsive grid (3 columns on desktop, 2 on tablet, 1 on mobile)**:
- **Pending Reminders**: count from `GET /reminders?status=pending` (icon: Bell, color: purple). Show count of items in the `reminders` array.
- **Active Tasks**: count from `GET /tasks?status=todo` + `GET /tasks?status=in_progress` (icon: CheckSquare, color: green)
- **Active Projects**: count from `GET /projects?status=active` (icon: FolderOpen, color: orange)
- **Monthly Expenses**: total from `GET /financial/report` for current month/year (icon: DollarSign, color: red). Display as "SAR {total}".
- **Graph Nodes**: total_nodes from `GET /graph/stats` (icon: Network, color: blue)
- **Inventory Items**: count from `GET /inventory` (icon: Package, color: teal)

**Second row — 2 cards side by side (stack on mobile)**:
- **Left: Upcoming Reminders** — List the first 5 pending reminders sorted by due_date from `GET /reminders?status=pending`. Each shows title, due_date (formatted relative like "in 2 hours" / "tomorrow"), priority as colored dots (1=gray, 2=blue, 3=yellow, 4=orange, 5=red), and reminder_type as a small badge. Clicking a reminder navigates to the Reminders page.
- **Right: Today's Plan** — Fetch `GET /proactive/morning-summary`. Show the `daily_plan` text rendered with Arabic formatting and any `spending_alerts`. Show `timeblock_suggestion.blocks` as a simple timeline if available.

**Third row — 2 cards**:
- **Left: Expense Breakdown (current month)** — Pie chart (Recharts) from `GET /financial/report` using `by_category` array. Each slice is a category with label and SAR amount. Show legend below.
- **Right: Graph Stats** — Bar chart from `GET /graph/stats` using `by_type` dictionary. X-axis = entity type names, Y-axis = count. Color bars using the entity type palette above.

**Fourth row — 1 full-width card**:
- **Debt Summary** — From `GET /financial/debts`. Show 3 values prominently: `total_i_owe` (red), `total_owed_to_me` (green), `net_position` (blue or red depending on sign). Below, list individual debts (person, amount, direction, reason, status) in a compact table.

---

### PAGE 2: CHAT (`/chat`)

A full-screen chat interface for conversing with the RAG AI.

**Layout**: Full height (calc 100vh - header). Left side: chat area. No sidebar content needed.

**Chat area**:
- Message list with user messages on the right (styled with a colored bubble, e.g., blue) and assistant messages on the left (gray bubble). Support RTL text in both.
- Each assistant message may contain Arabic text with emojis. Render markdown formatting (bold, lists, links).
- Show tool call badges below assistant messages — if `tool_calls` array is non-empty, show small badges like "search_knowledge", "create_reminder", etc.
- At the bottom: text input with a send button. On Enter or click, POST to `/chat/v2` with `{"message": inputText, "session_id": "dashboard"}`. Show a typing indicator while waiting.
- Store messages in component state (not persisted). Show a "Clear" button to reset.
- Show the `reply` field from the response in the assistant bubble.

**Streaming alternative**: Toggle between streaming and non-streaming mode. For streaming, POST to `/chat/v2/stream` and parse NDJSON lines:
  - `{"type":"meta", ...}` — show status
  - `{"type":"token", "content":"..."}` — append to current assistant message
  - `{"type":"done"}` — finalize message

**Conversation Summary button**: Clicking it calls `GET /chat/summary?session_id=dashboard` and shows the summary in a Dialog.

---

### PAGE 3: REMINDERS (`/reminders`)

**Top bar**:
- Filter tabs: All | Pending | Done | Snoozed — maps to `GET /reminders?status=` (no status for all, `pending`, `done`, `snoozed`)
- Button: "Merge Duplicates" — calls `POST /reminders/merge-duplicates`, shows result toast
- Button: "Delete All Done" — calls `POST /reminders/delete-all?status=done` with confirmation dialog

**Reminder list**: Card-based list (not table). Each card shows:
- **Title** (large, bold, Arabic)
- **Due date**: formatted as Arabic relative time + absolute date. Color: red if overdue, orange if today, green if future.
- **Status badge**: pending (yellow), done (green), snoozed (blue)
- **Type badge**: one_time, recurring, persistent, event_based, financial — each a different color
- **Priority**: 1-5 shown as star rating or colored indicator
- **Recurrence**: if set, show "يومي/أسبوعي/شهري/سنوي" badge
- **Persistent**: if true, show a pin icon
- **Location**: if `location_place` or `location_type` is set, show a MapPin icon with the place name
- **Description**: truncated, expandable
- **Snooze count**: if >0, show "snoozed X times"

**Card actions** (3-dot menu or action buttons):
- **Mark Done**: `POST /reminders/action` with `{"title": "...", "action": "done"}`
- **Snooze**: Opens a dialog to pick snooze duration (30min, 1hr, 3hr, tomorrow, custom datetime). Calls `POST /reminders/action` with `{"title": "...", "action": "snooze", "snooze_until": "ISO datetime"}`
- **Cancel**: `POST /reminders/action` with `{"title": "...", "action": "cancel"}`
- **Edit**: Opens a dialog with fields: title, due_date (datetime picker), priority (1-5 select), description (textarea), recurrence (select: none, daily, weekly, monthly, yearly). Saves via `POST /reminders/update`.
- **Delete**: Confirmation dialog, then `POST /reminders/delete` with `{"title": "..."}`

---

### PAGE 4: TASKS (`/tasks`)

**Top bar**:
- Filter tabs: All | To Do | In Progress | Done | Cancelled — maps to `GET /tasks?status=`
- Button: "Merge Duplicates" — calls `POST /tasks/merge-duplicates`

**Task list**: Kanban board view (3 columns: To Do, In Progress, Done) OR list view (toggleable).

**Kanban view**: Each column shows task cards. Cards display:
- Title (bold)
- Priority (1-5, colored dot)
- Due date (relative)
- Project name (linked badge)
- Energy level if set (high/medium/low with icon)
- Estimated duration if set ("30 min")

**Card actions**:
- **Update Status**: Quick action buttons to move between columns. Calls `POST /tasks/update` with `{"title": "...", "status": "in_progress"}`
- **Edit**: Dialog with fields: title, status (select), due_date, priority (1-5), project (text input). Calls `POST /tasks/update`.
- **Delete**: `POST /tasks/delete` with `{"title": "..."}`

**List view**: Table with columns: Title, Status, Priority, Due Date, Project, Actions.

---

### PAGE 5: PROJECTS (`/projects`)

**Top bar**:
- Filter by status: All | Idea | Planning | Active | Paused | Done | Cancelled — `GET /projects?status=`

**Project cards grid** (2-3 columns):
Each card shows:
- Project name (large)
- Status badge (idea=gray, planning=blue, active=green, paused=yellow, done=teal, cancelled=red)
- Priority (1-5)
- Description (truncated)
- Click opens detail view

**Card actions**:
- **Edit**: Dialog → `POST /projects/update` with `{"name": "...", "status": "...", "description": "...", "priority": N}`
- **Delete**: `POST /projects/delete` with `{"name": "..."}`
- **Focus**: `POST /projects/focus` with `{"name": "..."}`
- **Unfocus**: `POST /projects/unfocus`

**Project Detail view** (clicking a card or using route `/projects/:name`):
- Fetch `GET /projects/details?name=ProjectName`
- Show full details text (returned as formatted string)
- Show linked tasks below (sections, lists, etc.)

**Merge Dialog**: Select multiple projects, choose target → `POST /projects/merge` with `{"sources": [...], "target": "..."}`

---

### PAGE 6: FINANCIAL (`/financial`)

**Three tabs**: Expenses | Debts | Alerts

**Expenses tab**:
- Month/Year picker (default: current). Calls `GET /financial/report?month=M&year=Y`
- Show total prominently: "SAR {total}"
- Pie chart of `by_category` (Recharts PieChart)
- Table below: Category | Total (SAR) | Count | Percentage
- Toggle "Compare with previous month": adds `&compare=true` and shows `comparison` data as a grouped bar chart (this month vs last month per category)

**Debts tab**:
- Fetch `GET /financial/debts`
- Three summary cards: "I Owe" (red), "Owed to Me" (green), "Net Position" (color by sign)
- Debt list table: Person | Amount (SAR) | Direction (i_owe/owed_to_me with arrow icons) | Reason | Status (open/partial/paid) | Date
- **Record Payment** button: Dialog with fields: person (text), amount (number), direction (select). Calls `POST /financial/debts/payment`.

**Alerts tab**:
- Fetch `GET /financial/alerts`
- Display `alerts` text in a card with warning styling

---

### PAGE 7: INVENTORY (`/inventory`)

**Top bar**:
- Search input (filters via `GET /inventory?search=query`)
- Category filter (text input or select, `GET /inventory?category=cat`)
- Buttons: "Report", "Unused Items", "Duplicates"

**Item list**: Cards or table showing inventory items. Fields depend on returned text format (the API returns structured text).

**Add Item** button: Dialog with fields:
- name (text, required)
- quantity (number, default 1)
- location (text)
- category (text)
- condition (text)
- brand (text)
- description (textarea)
Calls `POST /inventory/item`.

**Report**: `GET /inventory/report` — show in a Dialog or dedicated card.

**Unused Items**: `GET /inventory/unused?days=90` — show list with threshold.

**Duplicates**: `GET /inventory/duplicates?method=name` — show pairs with option to merge. Also support `method=vector`.

**Similar Search**: Dialog with description textarea → `POST /inventory/search-similar` → show results with scores.

---

### PAGE 8: KNOWLEDGE (`/knowledge`)

- Fetch `GET /knowledge` (optional topic filter: `GET /knowledge?topic=X`)
- Topic filter input at top
- Display knowledge entries in cards with title, content, source, category
- Searchable/filterable list

---

### PAGE 9: MAP & PLACES (`/location`)

This is a critical page with a full interactive map.

**Layout**: Full-width map taking 70% height, place list panel below (or side panel on desktop).

**Map** (use `react-leaflet` with Leaflet.js):
- **Tile layers**:
  - Default: OpenStreetMap (`https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`)
  - Satellite: Esri World Imagery (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`)
  - Layer toggle control in top-right corner of the map
- **Default center**: Saudi Arabia (lat: 24.7136, lon: 46.6753), zoom 6. If current position available, center on it.
- **Current position**: Fetch `GET /location/current`. If `position` has lat/lon, show a pulsing blue dot marker. Show `current_zones` as a tooltip.
- **Saved places**: Fetch `GET /location/places`. For each place, render:
  - A **marker** at (lat, lon) with a popup showing: name, place_type, address, radius
  - A **circle** overlay showing the geofence radius (in meters). Circle color based on place_type or default blue, semi-transparent fill.
- **Place type icons in markers**: Use different colored markers or icons for different Arabic place types:
  - بقالة (grocery), صيدلية (pharmacy), مطعم (restaurant), كافيه (cafe), مول (mall), مسجد (mosque), بنزينة (gas station), بنك (bank), مستشفى (hospital), مدرسة (school), حديقة (park), مغسلة (laundry), مكتبة (library)
- **Click to add**: Clicking on the map opens a dialog pre-filled with the clicked coordinates. Fields: name, lat, lon, radius (default 150m), place_type (select from the Arabic types above), address. Saves via `POST /location/places`.
- **Edit place**: Click a marker's popup, then click "Edit" button. Opens dialog with current values. Saves via `POST /location/places` (upsert by name).
- **Delete place**: In the popup, "Delete" button → confirmation → `DELETE /location/places/{name}`
- **Drag markers** to update position (save via `POST /location/places` with new lat/lon on dragend)
- **Editable circles**: If the library supports it, allow dragging circle edges to adjust radius. Otherwise, provide a radius slider in the edit dialog.

**Place type filter**: Dropdown to filter by `place_type` → `GET /location/places?place_type=مسجد`

**Places list panel**: Below or beside the map. Table or card list of all places with: Name, Type, Address, Radius, Coordinates, Actions (Edit, Delete, Zoom To). "Zoom To" centers the map on that place.

---

### PAGE 10: SPRINTS & PRODUCTIVITY (`/productivity`)

**Three tabs**: Sprints | Focus Sessions | Time Blocking

**Sprints tab**:
- Filter by status: All | Planning | Active | Completed | Cancelled → `GET /productivity/sprints/?status=`
- Sprint cards showing: name, status, start_date, end_date, goal, project
- **Create Sprint** button: Dialog with name, project, start_date, end_date, goal → `POST /productivity/sprints/`
- **Sprint Detail**: Click card → shows burndown chart from `GET /productivity/sprints/{name}/burndown`
- **Complete Sprint**: Button → `POST /productivity/sprints/{name}/complete`
- **Assign Task**: Button → dialog to pick task name → `POST /productivity/sprints/{sprint}/tasks/{task}`
- **Velocity chart**: Card showing `GET /productivity/sprints/velocity` with optional project filter

**Focus Sessions tab**:
- **Start Focus** button: Dialog with task (optional), duration_minutes (default 25). Calls `POST /productivity/focus/start`.
- **Complete Focus** button: Calls `POST /productivity/focus/complete` with `{"completed": true}`.
- **Stats**: Fetch `GET /productivity/focus/stats`. Display:
  - Today: sessions count, minutes
  - This week: sessions count, minutes
  - Total: sessions count, minutes
  - By task: bar chart of minutes per task

**Time Blocking tab**:
- Date picker (default today)
- Energy override: select (normal, tired, energized)
- **Suggest** button: `POST /productivity/timeblock/suggest` with `{"date": "YYYY-MM-DD", "energy_override": "..."}`. Show returned `blocks` as a vertical timeline/schedule (time slots with task names, styled by energy level).
- **Apply** button: `POST /productivity/timeblock/apply` with the blocks data.

---

### PAGE 11: GRAPH EXPLORER (`/graph`)

**Layout**: Full-width interactive graph visualization.

**Controls bar** at top:
- Entity type filter: Dropdown select (Person, Project, Task, Expense, Debt, Reminder, Company, Item, Knowledge, Topic, Tag, Sprint, Idea, FocusSession, Place). When selected, fetches `GET /graph/export?entity_type=TYPE&limit=500`.
- Center entity: Text input. When submitted, fetches `GET /graph/export?center=NAME&hops=2&limit=500`.
- Hops slider: 1-5 (default 2). Only active when center entity is set.
- Limit input: number (default 500, max 5000).
- "Full Graph" button: `GET /graph/export?limit=500`
- "Download PNG" button: `POST /graph/image` with current filters, receives PNG blob, triggers download.

**Graph visualization**: Use a force-directed graph library — prefer `react-force-graph-2d` (from `react-force-graph`) or `@react-sigma/core` (Sigma.js). The API returns:
```json
{
  "nodes": [{"id": 123, "label": "...", "type": "Person", "properties": {...}}],
  "edges": [{"source": 123, "target": 456, "type": "KNOWS", "properties": {...}}]
}
```

- **Node rendering**: Circle with color from the entity type palette. Label shown as text next to node (support Arabic text).
- **Edge rendering**: Directed arrow with relationship type label on hover.
- **Node hover/click**: Show tooltip or side panel with all `properties` as a key-value list.
- **Zoom/pan**: Standard graph controls.
- **Node size**: Scale by connection count.

**Schema sidebar** (toggleable):
- Fetch `GET /graph/schema`
- Show `node_labels` as a list with counts and colored dots
- Show `relationship_types` as a list with counts
- Show totals: total_nodes, total_edges

**Stats card** below or in sidebar:
- Fetch `GET /graph/stats`
- Bar chart of `by_type` counts

---

### PAGE 12: SEARCH (`/search`)

**Search bar** (prominent, full width):
- Query input (large, Arabic placeholder: "ابحث في قاعدة المعرفة...")
- Source select: Auto | Vector | Graph
- Limit: number input (default 5)
- Search button

On submit, `POST /search` with `{"query": "...", "source": "auto", "limit": 5}`.

**Results**: List of result cards. Each shows:
- `text` (the matching content, with highlighted query terms if possible)
- `score` (as a percentage bar or badge)
- `source` (badge: "vector" or "graph")
- `metadata` (collapsible section showing key-value pairs)

Show `source_used` at the top of results.

---

### PAGE 13: INGEST (`/ingest`)

**Three tabs**: Text | File | URL

**Text tab**:
- Textarea for content
- Source type select: note, conversation, document, etc.
- Tags input (comma-separated)
- Topic input (text)
- Submit button → `POST /ingest/text` with `{"text": "...", "source_type": "note", "tags": [...], "topic": "..."}`
- Show result: chunks_stored, facts_extracted, entities list

**File tab**:
- File drop zone (drag & drop + click to browse)
- Context input (caption describing the file)
- Tags input (comma-separated)
- Topic input
- Progress indicator during upload
- Submit → `POST /ingest/file` (multipart form data with file, context, tags, topic)
- Show result: filename, file_type, file_hash, analysis, chunks_stored, facts_extracted, entities, auto_expense, auto_item

**URL tab**:
- URL input
- Context input (what this URL is about)
- Tags input
- Topic input
- Submit → `POST /ingest/url` with `{"url": "...", "context": "...", "tags": [...], "topic": "..."}`
- Show result: status, chunks_stored, facts_extracted, entities

---

### PAGE 14: PROACTIVE (`/proactive`)

**Three sections/cards**:

**Morning Summary**:
- Fetch `GET /proactive/morning-summary`
- Show `daily_plan` text (render as formatted Arabic text with line breaks)
- Show `spending_alerts` if present (in a warning card)
- Show `timeblock_suggestion.blocks` as a timeline if present

**Noon Check-in**:
- Fetch `GET /proactive/noon-checkin`
- Show `overdue_reminders` list with title, due_date, priority, description
- Each reminder gets a red "overdue" badge

**Evening Summary**:
- Fetch `GET /proactive/evening-summary`
- Show `completed_today` as a checklist (checkmarks)
- Show `tomorrow_reminders` as upcoming cards

**Additional sections**:
- **Stalled Projects**: Fetch `GET /proactive/stalled-projects?days=14`. Show project cards with name, status, last_activity, task_count. Adjustable days threshold slider.
- **Old Debts**: Fetch `GET /proactive/old-debts?days=30`. Show debt cards with person, amount, reason, created_at, status. Adjustable days slider.
- **Due Reminders**: Fetch `GET /proactive/due-reminders`. Show list of currently due reminders with all fields. Mark notified button → `POST /proactive/mark-notified`.

---

### PAGE 15: USER MANAGEMENT (`/admin/users`) — Admin Only

**Top bar**: "Register User" button

**User list table** (fetch `GET /admin/users`):
Columns: User ID | Display Name | Graph Name | Collection | TG Chat ID | Enabled | Actions

**Register User Dialog**:
- Fields: user_id (required), display_name, tg_chat_id, graph_name (auto-generated if empty), collection_name, redis_prefix
- Submit → `POST /admin/users`
- On success, show the generated API key in a copyable field with a warning "Save this key, it won't be shown again"

**User Actions**:
- **Lookup by Telegram**: Input TG ID → `GET /admin/users/by-telegram/{tg_id}` → show profile
- **Disable User**: Confirmation → `DELETE /admin/users/{user_id}` (soft delete)

---

### PAGE 16: BACKUP (`/backup`)

**Actions**:
- **Create Backup** button → `POST /backup/create` → show result (path, sizes, old_backups_removed) in toast/card
- **Backup List**: Fetch `GET /backup/list`. Table showing timestamp, files included, size.
- **Restore**: Each backup row has a "Restore" button → confirmation dialog → `POST /backup/restore/{timestamp}` → show result

---

### PAGE 17: SETTINGS (`/settings`)

A read-only settings reference page showing current system configuration. Since there is no settings update API, this is informational.

**Sections** (cards):
- **System Info**: Show a health check indicator (try `GET /health`), API base URL, timezone (UTC+3 Riyadh)
- **Configuration Reference**: Show key config values as a reference table:
  - Location: enabled, default_radius, cooldown_minutes
  - Prayer: city, country, offset_minutes
  - Proactive: enabled, morning/noon/evening hours, reminder_check_minutes
  - Backup: enabled, hour, retention_days
  - Productivity: pomodoro_default_minutes, sprint_default_weeks, energy_peak_hours
  - Inventory: unused_days, report_top_n
  - Multi-Tenancy: enabled, default_user_id
  - Auto-extract: enabled

  (These are displayed as static reference. Actual values come from the server; since there is no config endpoint, display them as a formatted reference guide.)

- **API Key Configuration**: Inputs for API Key and Admin Key that save to localStorage and update the global apiClient headers. Provide a "Test Connection" button that calls `GET /graph/stats` and shows success/failure.

---

### ROUTING

Use React Router v6 with these routes:
```
/                    → Dashboard
/chat                → Chat
/reminders           → Reminders
/tasks               → Tasks
/projects            → Projects
/projects/:name      → Project Detail
/financial           → Financial
/inventory           → Inventory
/knowledge           → Knowledge
/location            → Map & Places
/productivity        → Productivity (Sprints, Focus, Time Blocking)
/graph               → Graph Explorer
/search              → Search
/ingest              → Ingest
/proactive           → Proactive
/admin/users         → User Management
/backup              → Backup
/settings            → Settings
```

---

### DATA FETCHING

Use React Query (TanStack Query) for all data fetching:
- Cache keys should be descriptive (e.g., `["reminders", status]`, `["financial-report", month, year]`)
- Stale time: 30 seconds for most queries, 5 minutes for graph/stats
- Show loading skeletons during fetch
- Show error states with retry buttons
- Mutations should invalidate relevant queries on success

---

### ADDITIONAL NOTES

- All money amounts are in SAR (Saudi Riyal). Format with Arabic-Indic numerals optionally, but always show "SAR" or "ر.س".
- All dates should be formatted considering Arabic locale. Show both Gregorian and optionally Hijri dates where relevant.
- The API returns text content primarily in Arabic. Ensure proper text rendering, line breaks, and bidirectional text handling.
- The `GET /reminders`, `GET /tasks`, `GET /projects`, `GET /inventory`, and `GET /knowledge` endpoints return their data as a text string in their respective fields (reminders, tasks, projects, items, knowledge). Parse these as structured text or display as formatted text. Some may return JSON arrays or formatted text strings — handle both cases gracefully.
- For the map page, install `react-leaflet` and `leaflet` as dependencies. Include Leaflet CSS.
- For the graph visualization, install `react-force-graph-2d` as a dependency.
- Error handling: If any API call fails with 403, show a "Configure API Key" prompt directing to Settings page. If 404, show "Not Found". If 500, show "Server Error" with the detail message.
