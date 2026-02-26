"""
MCP Server for Claude Desktop (stdio transport).

Standalone process — 25 direct REST tools, no double-LLM.
Claude Desktop handles Arabic, date parsing, and reasoning natively.
"""

import logging
import sys
from pathlib import Path

import httpx
from fastmcp import FastMCP

logging.basicConfig(
    filename="/tmp/mcp_desktop.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("mcp_desktop")

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import get_settings

settings = get_settings()

API_BASE = f"http://localhost:{settings.api_port}"
TIMEOUT = 60.0

mcp = FastMCP(
    "Personal Life RAG",
    instructions=(
        "أنت مساعد شخصي ذكي لإدارة الحياة اليومية. "
        "تتكلم بالسعودية (اللهجة السعودية). "
        "استخدم الأدوات لتنفيذ الطلبات — لا تخترع بيانات من عندك. "
        "إذا ما لقيت نتائج، قل ما لقيت بصراحة."
    ),
)


# --- Helpers ---

async def api_get(path: str, params: dict | None = None) -> dict:
    log.info("GET %s params=%s", path, params)
    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT) as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            log.info("GET %s → %s", path, resp.status_code)
            return resp.json()
    except Exception as e:
        log.error("GET %s FAILED: %s", path, e)
        raise


async def api_post(path: str, json: dict | None = None) -> dict:
    log.info("POST %s json=%s", path, json)
    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT) as client:
            resp = await client.post(path, json=json)
            resp.raise_for_status()
            log.info("POST %s → %s", path, resp.status_code)
            return resp.json()
    except Exception as e:
        log.error("POST %s FAILED: %s", path, e)
        raise


# ============================================================
# Reminders (7 tools)
# ============================================================

@mcp.tool()
async def get_reminders(status: str = "") -> str:
    """Get reminders list. Returns all active reminders by default.

    Args:
        status: Optional filter — 'pending', 'done', or 'snoozed'. Empty = all active.
    """
    params = {"status": status} if status else None
    data = await api_get("/reminders/", params=params)
    return data.get("reminders", "No reminders.")


@mcp.tool()
async def create_reminder(
    title: str,
    due_date: str = "",
    time: str = "",
    recurrence: str = "",
    priority: int = 0,
    prayer: str = "",
) -> str:
    """Create a new reminder. Uses the tool-calling endpoint for reliable creation.

    Args:
        title: What to be reminded about (Arabic or English).
        due_date: Due date in ISO format, e.g. '2026-02-20'. Empty = no date.
        time: Time in HH:MM format, e.g. '14:30'. Empty = no specific time.
        recurrence: Repeat pattern — 'daily', 'weekly', 'monthly', 'yearly'. Empty = one-time.
        priority: Priority 1-5 (5=critical). 0 = default.
        prayer: Prayer time — 'fajr', 'dhuhr', 'asr', 'maghrib', 'isha'. Automatically calculates time. Use when user says 'بعد صلاة العصر' etc.
    """
    # Build structured Arabic message for the tool-calling endpoint
    parts = [f"ذكرني: {title}"]
    if prayer:
        _PRAYER_AR = {"fajr": "الفجر", "dhuhr": "الظهر", "asr": "العصر", "maghrib": "المغرب", "isha": "العشاء"}
        parts.append(f"بعد صلاة {_PRAYER_AR.get(prayer, prayer)}")
    if due_date:
        parts.append(f"تاريخ: {due_date}")
    if time:
        parts.append(f"وقت: {time}")
    if recurrence:
        parts.append(f"تكرار: {recurrence}")
    if priority:
        parts.append(f"أولوية: {priority}")

    message = " | ".join(parts)
    result = await api_post("/chat/v2", json={"message": message, "session_id": "claude-desktop"})

    # Extract tool results from agentic_trace
    trace = result.get("agentic_trace", [])
    for step in trace:
        if step.get("step") == "tool_calls":
            tools = step.get("tools", [])
            for t in tools:
                if t.get("name") == "create_reminder":
                    tool_result = t.get("result", {})
                    if tool_result.get("status") == "created":
                        return f"Reminder created: {tool_result.get('title', title)}"
                    return f"Error: {tool_result.get('error', 'Unknown error')}"

    # Fallback to reply text
    return result.get("reply", "Reminder creation sent.")


@mcp.tool()
async def update_reminder(
    title: str,
    new_title: str = "",
    due_date: str = "",
    priority: int = 0,
    recurrence: str = "",
) -> str:
    """Update an existing reminder's properties.

    Args:
        title: Current reminder title to find (fuzzy matched).
        new_title: New title. Empty = keep current.
        due_date: New due date in ISO format. Empty = keep current.
        priority: New priority 1-5. 0 = keep current.
        recurrence: New recurrence — 'daily', 'weekly', 'monthly', 'yearly'. Empty = keep current.
    """
    payload: dict = {"title": title}
    if new_title:
        payload["new_title"] = new_title
    if due_date:
        payload["due_date"] = due_date
    if priority:
        payload["priority"] = priority
    if recurrence:
        payload["recurrence"] = recurrence
    data = await api_post("/reminders/update", json=payload)
    if data.get("error"):
        return f"Error: {data['error']}"
    return f"Updated: {data.get('title', title)}"


@mcp.tool()
async def complete_reminder(title: str, action: str = "done") -> str:
    """Mark a reminder as done or snooze it.

    Args:
        title: The reminder title or keyword to match.
        action: 'done' to complete, 'snooze' to postpone. Defaults to 'done'.
    """
    payload: dict = {"title": title, "action": action}
    data = await api_post("/reminders/action", json=payload)
    if data.get("error"):
        return f"Error: {data['error']}"
    return data.get("message", f"Reminder '{title}' marked as {action}.")


@mcp.tool()
async def delete_reminder(title: str) -> str:
    """Delete a reminder by title (fuzzy matched).

    Args:
        title: The reminder title or keyword to match.
    """
    data = await api_post("/reminders/delete", json={"title": title})
    if data.get("error"):
        return f"Error: {data['error']}"
    deleted = data.get("deleted", [])
    if isinstance(deleted, list):
        return f"Deleted {len(deleted)} reminder(s): {', '.join(deleted)}"
    return f"Deleted {deleted} reminder(s)."


@mcp.tool()
async def merge_duplicate_reminders() -> str:
    """Find and merge duplicate reminders. Keeps the best one (earliest due_date, highest priority) and removes the rest."""
    data = await api_post("/reminders/merge-duplicates")
    groups = data.get("merged_groups", [])
    total = data.get("total_removed", 0)
    if not groups:
        return "No duplicate reminders found."
    lines = [f"Merged {total} duplicate(s) across {len(groups)} group(s):"]
    for g in groups:
        lines.append(f"- Kept: {g['kept']} (removed {g['removed_count']})")
    return "\n".join(lines)


@mcp.tool()
async def delete_all_reminders(status: str = "") -> str:
    """Delete all reminders, optionally filtered by status.

    Args:
        status: Optional filter — 'pending', 'done', or 'snoozed'. Empty = delete ALL reminders.
    """
    path = f"/reminders/delete-all?status={status}" if status else "/reminders/delete-all"
    data = await api_post(path, json=None)
    count = data.get("deleted_count", 0)
    label = f" with status '{status}'" if status else ""
    return f"Deleted {count} reminder(s){label}."


# ============================================================
# Financial (3 tools)
# ============================================================

@mcp.tool()
async def record_expense(
    description: str,
    amount: float,
    category: str = "",
    date: str = "",
    vendor: str = "",
) -> str:
    """Record an expense. Uses tool-calling endpoint for reliable storage.

    Args:
        description: What the expense was for (Arabic or English).
        amount: Amount in SAR.
        category: Category like 'food', 'transport', 'bills'. Empty = auto-detect.
        date: Date in ISO format. Empty = today.
        vendor: Where the money was spent. Empty = unknown.
    """
    parts = [f"صرفت {amount} ريال على {description}"]
    if category:
        parts.append(f"تصنيف: {category}")
    if date:
        parts.append(f"تاريخ: {date}")
    if vendor:
        parts.append(f"مكان: {vendor}")

    message = " | ".join(parts)
    result = await api_post("/chat/v2", json={"message": message, "session_id": "claude-desktop"})

    trace = result.get("agentic_trace", [])
    for step in trace:
        if step.get("step") == "tool_calls":
            tools = step.get("tools", [])
            for t in tools:
                if t.get("name") == "add_expense":
                    tool_result = t.get("result", {})
                    if tool_result.get("status") == "created":
                        return f"Expense recorded: {amount} SAR — {description}"
                    return f"Error: {tool_result.get('error', 'Unknown error')}"

    return result.get("reply", "Expense recording sent.")


@mcp.tool()
async def get_financial_report(month: int = 0, year: int = 0) -> str:
    """Get monthly spending report with category breakdown.

    Args:
        month: Month number 1-12. 0 = current month.
        year: Year. 0 = current year.
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


# ============================================================
# Knowledge & Search (3 tools)
# ============================================================

@mcp.tool()
async def search_knowledge(query: str) -> str:
    """Search the personal knowledge base using vector + graph search.

    Args:
        query: Search query in Arabic or English.
    """
    result = await api_post("/search/", json={"query": query, "source": "auto", "limit": 5})
    results = result.get("results", [])
    if not results:
        return "No results found."
    lines = [f"Search results ({result.get('source_used', 'auto')}):\n"]
    for r in results:
        score = f" [{r['score']:.2f}]" if r.get("score") else ""
        lines.append(f"- {r['text']}{score}")
    return "\n".join(lines)


@mcp.tool()
async def store_note(text: str, source_type: str = "note") -> str:
    """Store text in the knowledge base. Triggers full extraction pipeline — entities, facts, and relationships are automatically extracted and stored in the graph.

    Args:
        text: The text to store (Arabic or English).
        source_type: Type — 'note', 'knowledge', or 'idea'. Defaults to 'note'.
    """
    result = await api_post("/ingest/text", json={
        "text": text,
        "source_type": source_type,
        "tags": [],
    })
    chunks = result.get("chunks_stored", 0)
    facts = result.get("facts_extracted", 0)
    return f"Stored: {chunks} chunks, {facts} facts extracted."


@mcp.tool()
async def store_url(url: str, context: str = "") -> str:
    """Ingest content from a URL into the knowledge base. Supports GitHub repos, web pages, and articles.

    Args:
        url: Full URL (https://...).
        context: Optional context about what this URL is about.
    """
    payload: dict = {"url": url}
    if context:
        payload["context"] = context
    result = await api_post("/ingest/url", json=payload)
    chunks = result.get("chunks_stored", 0)
    facts = result.get("facts_extracted", 0)
    return f"Ingested URL: {chunks} chunks, {facts} facts extracted."


# ============================================================
# Planning & Overview (4 tools)
# ============================================================

@mcp.tool()
async def get_daily_plan() -> str:
    """Get today's daily plan — reminders, tasks, spending alerts, and time blocks."""
    data = await api_get("/proactive/morning-summary")
    lines = []

    daily_plan = data.get("daily_plan", "")
    if daily_plan:
        lines.append(daily_plan)

    alerts = data.get("spending_alerts")
    if alerts:
        lines.append(f"\nSpending alerts: {alerts}")

    timeblock = data.get("timeblock_suggestion")
    if timeblock and timeblock.get("blocks"):
        lines.append("\nSuggested time blocks:")
        for block in timeblock["blocks"]:
            lines.append(f"- {block['time']}: {block['task']} ({block['duration_minutes']}min)")

    return "\n".join(lines) if lines else "No plan data available for today."


@mcp.tool()
async def get_projects(status: str = "") -> str:
    """Get overview of all projects with task progress.

    Args:
        status: Optional filter — 'active', 'paused', 'idea', 'done'. Empty = all.
    """
    params = {"status": status} if status else None
    data = await api_get("/projects/", params=params)
    return data.get("projects", "No projects.")


@mcp.tool()
async def get_tasks(status: str = "") -> str:
    """Get all tasks with project links and status.

    Args:
        status: Optional filter — 'todo', 'in_progress', 'done'. Empty = all.
    """
    params = {"status": status} if status else None
    data = await api_get("/tasks/", params=params)
    return data.get("tasks", "No tasks.")


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


# ============================================================
# Projects (5 tools)
# ============================================================

@mcp.tool()
async def get_project_details(name: str) -> str:
    """Get full details of a project — sections, entities with descriptions, tasks, and lists.

    Args:
        name: Project name or keyword (fuzzy matched). Arabic names work too.
    """
    data = await api_get("/projects/details", params={"name": name})
    return data.get("details", f"No project found matching '{name}'.")


@mcp.tool()
async def focus_project(name: str) -> str:
    """Focus on a project — all subsequent queries will be scoped to this project.

    Args:
        name: Project name or keyword. Arabic names work too (e.g. 'الستيفنس').
    """
    data = await api_post("/projects/focus", json={"name": name, "session_id": "claude-desktop"})
    if data.get("error"):
        return f"Error: {data['error']}"
    return f"Focused on project: {data.get('project', name)}"


@mcp.tool()
async def unfocus_project() -> str:
    """Remove project focus — queries will no longer be scoped to any project."""
    data = await api_post("/projects/unfocus", json={"session_id": "claude-desktop"})
    return "Project focus cleared."


@mcp.tool()
async def delete_project(name: str) -> str:
    """Delete a project and all its linked tasks.

    Args:
        name: Project name or keyword to match (fuzzy).
    """
    data = await api_post("/projects/delete", json={"name": name})
    if data.get("error"):
        return f"Error: {data['error']}"
    tasks_del = data.get("tasks_deleted", 0)
    task_info = f" and {tasks_del} linked task(s)" if tasks_del else ""
    return f"Deleted project '{data.get('deleted', name)}'{task_info}."


@mcp.tool()
async def merge_projects(sources: list[str], target: str) -> str:
    """Merge multiple projects into one. Re-links all tasks to the target project and deletes the source projects.

    Args:
        sources: List of project names to merge FROM (will be deleted).
        target: Project name to merge INTO (will be kept/created).
    """
    data = await api_post("/projects/merge", json={"sources": sources, "target": target})
    moved = data.get("tasks_moved", 0)
    deleted = data.get("sources_deleted", 0)
    return f"Merged into '{target}': {deleted} project(s) deleted, {moved} task(s) moved."


# ============================================================
# Tasks (3 tools)
# ============================================================

@mcp.tool()
async def update_task(
    title: str,
    status: str = "",
    priority: int = 0,
    due_date: str = "",
    project: str = "",
) -> str:
    """Update an existing task's properties.

    Args:
        title: Current task title to find (fuzzy matched).
        status: New status — 'todo', 'in_progress', 'done', 'cancelled'. Empty = keep current.
        priority: New priority 1-5. 0 = keep current.
        due_date: New due date in ISO format. Empty = keep current.
        project: Link to project name. Empty = keep current.
    """
    payload: dict = {"title": title}
    if status:
        payload["status"] = status
    if priority:
        payload["priority"] = priority
    if due_date:
        payload["due_date"] = due_date
    if project:
        payload["project"] = project
    data = await api_post("/tasks/update", json=payload)
    if data.get("error"):
        return f"Error: {data['error']}"
    return f"Updated task: {data.get('title', title)} [{data.get('status', '?')}]"


@mcp.tool()
async def delete_task(title: str) -> str:
    """Delete a task by title (fuzzy matched).

    Args:
        title: The task title or keyword to match.
    """
    data = await api_post("/tasks/delete", json={"title": title})
    if data.get("error"):
        return f"Error: {data['error']}"
    deleted = data.get("deleted", [])
    if isinstance(deleted, list):
        return f"Deleted {len(deleted)} task(s): {', '.join(deleted)}"
    return f"Deleted {deleted} task(s)."


@mcp.tool()
async def merge_duplicate_tasks() -> str:
    """Find and merge duplicate tasks. Keeps the best one (highest priority, earliest due_date) and removes the rest."""
    data = await api_post("/tasks/merge-duplicates")
    groups = data.get("merged_groups", [])
    total = data.get("total_removed", 0)
    if not groups:
        return "No duplicate tasks found."
    lines = [f"Merged {total} duplicate(s) across {len(groups)} group(s):"]
    for g in groups:
        lines.append(f"- Kept: {g['kept']} (removed {g['removed_count']})")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
