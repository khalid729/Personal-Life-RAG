"""
MCP Server for Personal Life RAG.

Standalone process using FastMCP with SSE transport.
Runs on port 8600, calls RAG API at localhost:8500.
"""

import sys
from pathlib import Path

import httpx
from fastmcp import FastMCP

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import get_settings

settings = get_settings()

API_BASE = f"http://localhost:{settings.api_port}"
TIMEOUT = 60.0

mcp = FastMCP(
    "Personal Life RAG",
    instructions="Personal life management — finances, reminders, projects, tasks, knowledge",
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

    Args:
        message: The message to send (Arabic or English).
        session_id: Session ID for conversation continuity. Defaults to 'mcp'.
    """
    result = await api_post("/chat/", json={"message": message, "session_id": session_id})
    reply = result.get("reply", "")
    if result.get("pending_confirmation"):
        reply += "\n\n⚠️ Action requires confirmation — send 'نعم' (yes) or 'لا' (no) as the next message."
    return reply


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


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=settings.mcp_port)
