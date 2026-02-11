"""
MCP Server for Personal Life RAG.

Standalone process using FastMCP with SSE transport.
Runs on port 8600, calls RAG API at localhost:8500.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastmcp import FastMCP

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import get_settings

settings = get_settings()

API_BASE = f"http://localhost:{settings.api_port}"
TIMEOUT = 60.0

_DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
              4: "Friday", 5: "Saturday", 6: "Sunday"}


def _current_date_context() -> str:
    tz = timezone(timedelta(hours=settings.timezone_offset_hours))
    now = datetime.now(tz)
    day = _DAY_NAMES.get(now.weekday(), "")
    return f"Current date: {day}, {now.strftime('%Y-%m-%d %H:%M')} (UTC+{settings.timezone_offset_hours})"


mcp = FastMCP(
    "Personal Life RAG",
    instructions=(
        "Personal life management — finances, reminders, projects, tasks, knowledge, "
        "inventory, productivity, backup, graph visualization. "
        "IMPORTANT: When the chat tool returns 'PENDING_CONFIRMATION', the action has NOT been "
        "executed yet. Do NOT tell the user it was completed. Ask them to confirm with 'نعم' or 'لا'."
    ),
)


# --- Helpers ---

async def api_get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT) as client:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, json: dict | None = None) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT) as client:
        resp = await client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()


# --- Tools ---

@mcp.tool()
async def chat(message: str, session_id: str = "mcp") -> str:
    """Send a message to the Personal Life RAG system.
    Supports Arabic and English. Use for conversation, recording expenses/debts/reminders, or queries.

    CRITICAL RULES for interpreting the response:
    - ONLY say an action was completed if the response contains 'STATUS: ACTION_EXECUTED'
    - If response contains 'STATUS: PENDING_CONFIRMATION' → action NOT done yet, ask user to confirm
    - If response contains 'STATUS: CONVERSATION' → informational reply only, no data was modified
    - NEVER claim an action was performed (created/deleted/merged/updated) unless STATUS: ACTION_EXECUTED

    Args:
        message: The message to send (Arabic or English).
        session_id: Session ID for conversation continuity. Defaults to 'mcp'.
    """
    result = await api_post("/chat/", json={"message": message, "session_id": session_id})
    reply = result.get("reply", "")

    date_ctx = f"[{_current_date_context()}]\n\n"

    if result.get("pending_confirmation"):
        return (
            date_ctx
            + "STATUS: PENDING_CONFIRMATION — ACTION NOT YET EXECUTED.\n"
            "The system is asking for user confirmation. Do NOT tell the user it was completed.\n\n"
            + reply
            + "\n\n⚠️ Ask user to confirm: send 'نعم' (yes) or 'لا' (no) via this chat tool."
        )

    # Check if this was a confirmed action execution
    agentic_trace = result.get("agentic_trace", [])
    was_action = any(
        step.get("step") == "confirmed_action" for step in agentic_trace
    )
    if was_action:
        return date_ctx + f"STATUS: ACTION_EXECUTED — The action was confirmed and executed.\n\n{reply}"

    return date_ctx + f"STATUS: CONVERSATION — Informational reply. No data was modified.\n\n{reply}"


@mcp.tool()
async def search(query: str, source: str = "auto", limit: int = 5) -> str:
    """Search the personal knowledge base using vector and graph search.

    Args:
        query: Search query (Arabic or English).
        source: Search source — 'auto', 'vector', or 'graph'.
        limit: Maximum number of results (default 5).
    """
    result = await api_post("/search/", json={"query": query, "source": source, "limit": limit})
    results = result.get("results", [])
    if not results:
        return "No results found."
    lines = [f"Search results ({result.get('source_used', 'auto')}):\n"]
    for r in results:
        score = f"[{r['score']:.2f}]" if r.get("score") else ""
        lines.append(f"- {r['text']} {score}")
    return "\n".join(lines)


@mcp.tool()
async def create_reminder(text: str) -> str:
    """Create a new reminder via natural language.
    Examples: 'ذكرني أدفع الإيجار بكرة', 'remind me to call Ahmed tomorrow'.

    Args:
        text: Natural language description of the reminder (Arabic or English).
    """
    result = await api_post("/chat/", json={"message": text, "session_id": "mcp"})
    return result.get("reply", "")


@mcp.tool()
async def record_expense(text: str) -> str:
    """Record an expense via natural language.
    Examples: 'صرفت 200 على غداء', 'paid 50 SAR for coffee'.

    Args:
        text: Natural language description of the expense (Arabic or English).
    """
    result = await api_post("/chat/", json={"message": text, "session_id": "mcp"})
    return result.get("reply", "")


@mcp.tool()
async def get_financial_report(month: int = 0, year: int = 0) -> str:
    """Get monthly spending report with category breakdown.

    Args:
        month: Month number (1-12). Defaults to current month.
        year: Year. Defaults to current year.
    """
    params = {}
    if month:
        params["month"] = month
    if year:
        params["year"] = year
    data = await api_get("/financial/report", params=params or None)
    lines = [
        f"Financial Report — {data['month']}/{data['year']}",
        f"Total: {data['total']} {data['currency']}",
        "",
    ]
    for cat in data.get("by_category", []):
        lines.append(f"- {cat['category']}: {cat['total']} ({cat['percentage']}%)")
    if not data.get("by_category"):
        lines.append("No expenses this month.")
    return "\n".join(lines)


@mcp.tool()
async def get_debts() -> str:
    """Get summary of all debts — what you owe and what is owed to you."""
    data = await api_get("/financial/debts")
    lines = [
        "Debt Summary",
        f"You owe: {data['total_i_owe']} SAR",
        f"Owed to you: {data['total_owed_to_me']} SAR",
        f"Net position: {data['net_position']} SAR",
        "",
    ]
    for d in data.get("debts", []):
        direction = "you owe" if d.get("direction") == "i_owe" else "owes you"
        status = d.get("status", "open")
        reason = f" — {d['reason']}" if d.get("reason") else ""
        lines.append(f"- {d['person']}: {d['amount']} SAR ({direction}) [{status}]{reason}")
    if not data.get("debts"):
        lines.append("No active debts.")
    return "\n".join(lines)


@mcp.tool()
async def get_reminders() -> str:
    """Get all active reminders including overdue ones."""
    data = await api_get("/reminders/")
    return data.get("reminders", "No reminders.")


@mcp.tool()
async def delete_reminder(title: str) -> str:
    """Delete a reminder by title.

    Args:
        title: The reminder title or keyword to match.
    """
    data = await api_post("/reminders/delete", json={"title": title})
    if data.get("error"):
        return f"Error: {data['error']}"
    deleted = data.get("deleted", [])
    return f"Deleted {len(deleted)} reminder(s): {', '.join(deleted)}"


@mcp.tool()
async def update_reminder(title: str, new_title: str = "", due_date: str = "", priority: int = 0) -> str:
    """Update a reminder's properties.

    Args:
        title: Current reminder title to find.
        new_title: New title (empty = keep current).
        due_date: New due date in ISO format (empty = keep current).
        priority: New priority 1-5 (0 = keep current).
    """
    payload: dict = {"title": title}
    if new_title:
        payload["new_title"] = new_title
    if due_date:
        payload["due_date"] = due_date
    if priority:
        payload["priority"] = priority
    data = await api_post("/reminders/update", json=payload)
    if data.get("error"):
        return f"Error: {data['error']}"
    return f"Updated: {data.get('title', '?')} — Status: {data.get('status', '?')}"


@mcp.tool()
async def delete_all_reminders() -> str:
    """Delete ALL reminders. Use with caution."""
    data = await api_post("/reminders/delete-all")
    return f"Deleted {data.get('deleted_count', 0)} reminders."


@mcp.tool()
async def merge_duplicate_reminders() -> str:
    """Find and merge duplicate reminders. Keeps one copy per unique title."""
    data = await api_post("/reminders/merge-duplicates")
    groups = data.get("merged_groups", [])
    total = data.get("total_removed", 0)
    if not groups:
        return "No duplicates found to merge."
    lines = [f"Merged duplicates — removed {total} duplicate reminders:\n"]
    for g in groups:
        lines.append(f"- {g['kept']} (kept) — removed {g['removed_count']} copies")
    return "\n".join(lines)


@mcp.tool()
async def get_projects(status: str = "") -> str:
    """Get overview of all projects with task progress.

    Args:
        status: Optional filter — 'active', 'paused', 'idea', 'done'.
    """
    params = {"status": status} if status else None
    data = await api_get("/projects/", params=params)
    return data.get("projects", "No projects.")


@mcp.tool()
async def get_tasks(status: str = "") -> str:
    """Get all tasks with project links and status.

    Args:
        status: Optional filter — 'todo', 'in_progress', 'done'.
    """
    params = {"status": status} if status else None
    data = await api_get("/tasks/", params=params)
    return data.get("tasks", "No tasks.")


@mcp.tool()
async def get_knowledge(topic: str = "") -> str:
    """Get stored knowledge entries, optionally filtered by topic.

    Args:
        topic: Optional topic filter keyword.
    """
    params = {"topic": topic} if topic else None
    data = await api_get("/knowledge/", params=params)
    return data.get("knowledge", "No knowledge entries.")


@mcp.tool()
async def daily_plan() -> str:
    """Get today's daily plan — aggregates reminders, tasks, debts, and priorities."""
    result = await api_post("/chat/", json={"message": "رتب لي يومي", "session_id": "mcp"})
    return result.get("reply", "No plan available.")


@mcp.tool()
async def ingest_text(text: str, source_type: str = "note") -> str:
    """Store text information in the knowledge base.

    Args:
        text: The text to store (Arabic or English).
        source_type: Type of content — 'note', 'knowledge', 'idea'. Defaults to 'note'.
    """
    result = await api_post("/ingest/text", json={
        "text": text,
        "source_type": source_type,
        "tags": [],
    })
    return f"Stored: {result.get('chunks_stored', 0)} chunks, {result.get('facts_extracted', 0)} facts extracted."


# --- Inventory (Phase 7-9) ---


@mcp.tool()
async def get_inventory(search: str = "", category: str = "") -> str:
    """Get inventory items list.

    Args:
        search: Optional search keyword.
        category: Optional category filter.
    """
    params = {}
    if search:
        params["search"] = search
    if category:
        params["category"] = category
    data = await api_get("/inventory/", params=params or None)
    return data.get("items", "No inventory items.")


@mcp.tool()
async def get_inventory_report() -> str:
    """Get comprehensive inventory report with statistics by category, location, and condition."""
    data = await api_get("/inventory/report")
    lines = [
        f"Inventory Report",
        f"Total items: {data.get('total_items', 0)}",
        f"Total quantity: {data.get('total_quantity', 0)}",
        "",
    ]
    for cat in data.get("by_category", []):
        lines.append(f"- {cat.get('category', '?')}: {cat.get('items', 0)} items ({cat.get('quantity', 0)} units)")
    return "\n".join(lines)


# --- Productivity (Phase 10) ---


@mcp.tool()
async def get_sprints(status: str = "") -> str:
    """Get sprints list with progress information.

    Args:
        status: Optional filter — 'active', 'completed'.
    """
    params = {"status": status} if status else None
    data = await api_get("/productivity/sprints/", params=params)
    sprints = data.get("sprints", [])
    if not sprints:
        return "No sprints found."
    lines = ["Sprints:\n"]
    for s in sprints:
        name = s.get("name", "?")
        status_val = s.get("status", "?")
        lines.append(f"- {name} [{status_val}]")
    return "\n".join(lines)


@mcp.tool()
async def get_focus_stats() -> str:
    """Get focus session (pomodoro) statistics — total sessions, minutes, and completion rate."""
    data = await api_get("/productivity/focus/stats")
    return (
        f"Focus Stats\n"
        f"Sessions: {data.get('total_sessions', 0)}\n"
        f"Total minutes: {data.get('total_minutes', 0)}\n"
        f"Avg duration: {data.get('avg_duration', 0)} min\n"
        f"Completion rate: {data.get('completion_rate', 0)}%"
    )


# --- Backup (Phase 11) ---


@mcp.tool()
async def create_backup() -> str:
    """Create a full system backup of graph database, vector store, and Redis memory."""
    data = await api_post("/backup/create")
    sizes = data.get("sizes", {})
    return (
        f"Backup created: {data.get('timestamp', '?')}\n"
        f"Graph: {sizes.get('graph', 0):,} bytes\n"
        f"Vector: {sizes.get('vector', 0):,} bytes\n"
        f"Redis: {sizes.get('redis', 0):,} bytes"
    )


@mcp.tool()
async def list_backups() -> str:
    """List all available system backups."""
    data = await api_get("/backup/list")
    backups = data.get("backups", [])
    if not backups:
        return "No backups available."
    lines = ["Available backups:\n"]
    for b in backups:
        lines.append(f"- {b.get('timestamp', '?')}")
    return "\n".join(lines)


# --- Graph Visualization (Phase 11) ---


@mcp.tool()
async def get_graph_schema() -> str:
    """Get knowledge graph schema — node labels, relationship types, and counts."""
    data = await api_get("/graph/schema")
    lines = [
        f"Graph Schema",
        f"Nodes: {data.get('total_nodes', 0)}",
        f"Edges: {data.get('total_edges', 0)}",
        "",
        "Node types:",
    ]
    for label, count in data.get("node_labels", {}).items():
        lines.append(f"- {label}: {count}")
    lines.append("\nRelationship types:")
    for rel, count in data.get("relationship_types", {}).items():
        lines.append(f"- {rel}: {count}")
    return "\n".join(lines)


@mcp.tool()
async def get_graph_stats() -> str:
    """Get knowledge graph statistics — total nodes, edges, and counts by type."""
    data = await api_get("/graph/stats")
    lines = [
        f"Graph Stats",
        f"Total nodes: {data.get('total_nodes', 0)}",
        f"Total edges: {data.get('total_edges', 0)}",
        "",
    ]
    for node_type, count in data.get("by_type", {}).items():
        lines.append(f"- {node_type}: {count}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=settings.mcp_port)
