"""Proactive system endpoints — called by scheduler jobs in the Telegram bot."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/proactive", tags=["proactive"])

settings = get_settings()


def _now_local() -> datetime:
    """Current datetime in the configured timezone."""
    tz = timezone(timedelta(hours=settings.timezone_offset_hours))
    return datetime.now(tz)


# --- Request models ---


class AdvanceReminderRequest(BaseModel):
    title: str
    recurrence: str


# --- Endpoints ---


@router.get("/morning-summary")
async def morning_summary(request: Request):
    graph = request.app.state.retrieval.graph
    daily_plan = await graph.query_daily_plan()
    spending_alerts = await graph.query_spending_alerts()
    return {
        "daily_plan": daily_plan,
        "spending_alerts": spending_alerts or None,
    }


@router.get("/noon-checkin")
async def noon_checkin(request: Request):
    graph = request.app.state.retrieval.graph
    now_str = _now_local().isoformat()
    q = """
    MATCH (r:Reminder)
    WHERE r.status = 'pending'
      AND r.due_date IS NOT NULL
      AND r.due_date < $now
    RETURN r.title, r.due_date, r.reminder_type, r.priority, r.description
    ORDER BY r.due_date
    LIMIT 20
    """
    rows = await graph.query(q, {"now": now_str})
    overdue = []
    for r in rows or []:
        overdue.append({
            "title": r[0],
            "due_date": r[1],
            "reminder_type": r[2],
            "priority": r[3],
            "description": r[4],
        })
    return {"overdue_reminders": overdue}


@router.get("/evening-summary")
async def evening_summary(request: Request):
    graph = request.app.state.retrieval.graph
    now = _now_local()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_eod = tomorrow + "T23:59:59"

    # Tasks completed today
    q_completed = """
    MATCH (t:Task)
    WHERE t.status = 'done'
      AND t.updated_at IS NOT NULL
      AND t.updated_at >= $today
    RETURN t.title
    LIMIT 20
    """
    rows = await graph.query(q_completed, {"today": today})
    completed = [r[0] for r in rows or []]

    # Reminders completed today
    q_done_reminders = """
    MATCH (r:Reminder)
    WHERE r.status = 'done'
      AND r.completed_at IS NOT NULL
      AND r.completed_at >= $today
    RETURN r.title
    LIMIT 20
    """
    rows = await graph.query(q_done_reminders, {"today": today})
    completed.extend(r[0] for r in rows or [])

    # Tomorrow's reminders
    q_tomorrow = """
    MATCH (r:Reminder)
    WHERE r.status = 'pending'
      AND r.due_date IS NOT NULL
      AND r.due_date >= $tomorrow
      AND r.due_date <= $tomorrow_eod
    RETURN r.title, r.due_date, r.reminder_type, r.priority
    ORDER BY r.due_date
    LIMIT 20
    """
    rows = await graph.query(q_tomorrow, {"tomorrow": tomorrow, "tomorrow_eod": tomorrow_eod})
    tomorrow_reminders = []
    for r in rows or []:
        tomorrow_reminders.append({
            "title": r[0],
            "due_date": r[1],
            "reminder_type": r[2],
            "priority": r[3],
        })

    return {
        "completed_today": completed,
        "tomorrow_reminders": tomorrow_reminders,
    }


@router.get("/due-reminders")
async def due_reminders(request: Request):
    graph = request.app.state.retrieval.graph
    now_str = _now_local().isoformat()
    q = """
    MATCH (r:Reminder)
    WHERE r.status = 'pending'
      AND r.due_date IS NOT NULL
      AND r.due_date <= $now
    RETURN r.title, r.due_date, r.reminder_type, r.priority, r.description, r.recurrence
    ORDER BY r.due_date
    LIMIT 30
    """
    rows = await graph.query(q, {"now": now_str})
    reminders = []
    for r in rows or []:
        reminders.append({
            "title": r[0],
            "due_date": r[1],
            "reminder_type": r[2],
            "priority": r[3],
            "description": r[4],
            "recurrence": r[5],
        })
    return {"due_reminders": reminders}


@router.post("/advance-reminder")
async def advance_reminder(req: AdvanceReminderRequest, request: Request):
    graph = request.app.state.retrieval.graph
    result = await graph.advance_recurring_reminder(req.title, req.recurrence)
    return result


@router.get("/stalled-projects")
async def stalled_projects(request: Request, days: int = 14):
    graph = request.app.state.retrieval.graph
    cutoff = (_now_local() - timedelta(days=days)).isoformat()
    q = """
    MATCH (p:Project)
    WHERE p.status IS NULL OR p.status IN ['active', 'in_progress']
    OPTIONAL MATCH (t:Task)-[:BELONGS_TO]->(p)
    WITH p,
         max(coalesce(t.updated_at, p.updated_at, p.created_at)) as last_activity,
         count(t) as task_count
    WHERE last_activity < $cutoff
    RETURN p.name, p.status, last_activity, task_count
    ORDER BY last_activity
    LIMIT 20
    """
    rows = await graph.query(q, {"cutoff": cutoff})
    projects = []
    for r in rows or []:
        projects.append({
            "name": r[0],
            "status": r[1],
            "last_activity": r[2],
            "task_count": r[3],
        })
    return {"stalled_projects": projects, "days_threshold": days}


@router.get("/old-debts")
async def old_debts(request: Request, days: int = 30):
    graph = request.app.state.retrieval.graph
    cutoff = (_now_local() - timedelta(days=days)).isoformat()
    q = """
    MATCH (d:Debt)-[:INVOLVES]->(p:Person)
    WHERE d.status IN ['open', 'partial']
      AND d.direction = 'i_owe'
      AND d.created_at < $cutoff
    RETURN p.name, d.amount, d.reason, d.created_at, d.status
    ORDER BY d.amount DESC
    LIMIT 20
    """
    rows = await graph.query(q, {"cutoff": cutoff})
    debts = []
    for r in rows or []:
        debts.append({
            "person": r[0],
            "amount": r[1],
            "reason": r[2],
            "created_at": r[3],
            "status": r[4],
        })
    return {"old_debts": debts, "days_threshold": days}
