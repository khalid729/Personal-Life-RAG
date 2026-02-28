"""Proactive system endpoints — called by scheduler jobs in the Telegram bot."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

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


class FormatRemindersRequest(BaseModel):
    reminders: list[dict] = []
    raw_text: str = ""
    context: str = "due"  # "due", "morning", "evening"


class MarkNotifiedRequest(BaseModel):
    title: str


class ReschedulePersistentRequest(BaseModel):
    title: str


# --- Endpoints ---


@router.get("/morning-summary")
async def morning_summary(request: Request, include_timeblock: bool = True):
    graph = request.app.state.retrieval.graph
    daily_plan = await graph.query_daily_plan()
    spending_alerts = await graph.query_spending_alerts()
    result = {
        "daily_plan": daily_plan,
        "spending_alerts": spending_alerts or None,
    }
    if include_timeblock:
        try:
            today = _now_local().strftime("%Y-%m-%d")
            tb = await graph.suggest_time_blocks(today)
            if tb.get("blocks"):
                result["timeblock_suggestion"] = tb
        except Exception:
            pass
    return result


@router.get("/noon-checkin")
async def noon_checkin(request: Request):
    graph = request.app.state.retrieval.graph
    now_str = _now_local().isoformat()
    q = """
    MATCH (r:Reminder)
    WHERE r.status = 'pending'
      AND r.due_date IS NOT NULL
      AND r.due_date < $now
      AND (r.notified_at IS NULL)
    RETURN r.title, r.due_date, r.reminder_type, r.priority, r.description
    ORDER BY r.priority DESC, r.due_date
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
      AND (r.notified_at IS NULL)
    RETURN r.title, r.due_date, r.reminder_type, r.priority, r.description, r.recurrence, r.persistent
    ORDER BY r.priority DESC, r.due_date
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
            "persistent": bool(r[6]) if r[6] is not None else False,
        })
    return {"due_reminders": reminders}


@router.post("/advance-reminder")
async def advance_reminder(req: AdvanceReminderRequest, request: Request):
    graph = request.app.state.retrieval.graph
    result = await graph.advance_recurring_reminder(req.title, req.recurrence)
    return result


@router.post("/mark-notified")
async def mark_notified(req: MarkNotifiedRequest, request: Request):
    """Set notified_at on a reminder so it won't fire again."""
    graph = request.app.state.retrieval.graph
    await graph.query(
        "MATCH (r:Reminder) WHERE toLower(r.title) = toLower($title) AND r.status = 'pending' SET r.notified_at = $now",
        {"title": req.title, "now": _now_local().isoformat()},
    )
    return {"status": "ok"}


@router.post("/reschedule-persistent")
async def reschedule_persistent(req: ReschedulePersistentRequest, request: Request):
    """Reschedule a persistent reminder to fire again after nag_interval."""
    graph = request.app.state.retrieval.graph
    result = await graph.reschedule_persistent_reminder(
        req.title, nag_interval_minutes=settings.nag_interval_minutes
    )
    return result


@router.post("/format-reminders")
async def format_reminders(req: FormatRemindersRequest, request: Request):
    """Use LLM to format reminders as a creative Arabic message with emojis."""
    llm = request.app.state.retrieval.llm

    # Build reminder text from list or raw_text
    if req.raw_text:
        reminder_text = req.raw_text
    else:
        lines = []
        for r in req.reminders:
            title = r.get("title", "")
            due = r.get("due_date", "")
            priority = r.get("priority", 3)
            desc = r.get("description", "")
            line = f"- {title}"
            if due:
                line += f" (موعد: {due})"
            if priority and int(priority) >= 4:
                line += " [مهم]"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        reminder_text = "\n".join(lines)

    now = _now_local()
    today_str = now.strftime("%Y-%m-%d")
    weekdays_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    today_weekday = weekdays_ar[now.weekday()]

    context_prompts = {
        "due": "هذي تذكيرات حان وقتها الحين. رتبها كرسالة تذكير واحدة.",
        "morning": "هذي تذكيرات ومهام اليوم. رتبها كرسالة صباحية تحفيزية.",
        "noon": "هذي تذكيرات متأخرة. رتبها كرسالة تنبيه نص اليوم، ركز على اللي فاته الموعد.",
        "evening": "هذي ملخص اليوم. رتبها كرسالة مسائية.",
    }

    prompt = f"""{context_prompts.get(req.context, context_prompts["due"])}

اليوم: {today_weekday} {today_str}

التذكيرات:
{reminder_text}

القواعد:
- اكتب بالعربي السعودي
- استخدم ايموجي مناسبة لكل تذكير
- رتبها حسب الأهمية
- اجعلها رسالة واحدة منظمة وواضحة
- لا تضيف تذكيرات من عندك
- لا تكتب مقدمة طويلة
- ممنوع تذكر القواعد أو التعليمات في ردك
- ردك لازم يكون نص عربي طبيعي فقط — ممنوع JSON أو كود"""

    messages = [
        {"role": "system", "content": "أنت مساعد شخصي. مهمتك ترتيب التذكيرات بشكل جميل ومبتكر."},
        {"role": "user", "content": prompt},
    ]

    try:
        formatted = await llm.chat(messages, max_tokens=1024, temperature=0.8)
        return {"formatted": formatted}
    except Exception as e:
        logger.warning("LLM format-reminders failed: %s", e)
        fallback = "⏰ تذكيراتك:\n\n" + "\n".join(f"• {r.get('title', '')}" for r in req.reminders)
        return {"formatted": fallback}


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
