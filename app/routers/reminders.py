from fastapi import APIRouter, Request

from app.models.schemas import ReminderActionRequest, ReminderDeleteRequest, ReminderUpdateRequest

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/")
async def list_reminders(request: Request, status: str | None = None):
    graph = request.app.state.retrieval.graph
    text = await graph.query_reminders(status=status)
    return {"reminders": text}


@router.post("/action")
async def reminder_action(req: ReminderActionRequest, request: Request):
    graph = request.app.state.retrieval.graph
    snooze_str = req.snooze_until.isoformat() if req.snooze_until else None
    result = await graph.update_reminder_status(
        title=req.title,
        action=req.action,
        snooze_until=snooze_str,
    )
    return result


@router.post("/update")
async def update_reminder(req: ReminderUpdateRequest, request: Request):
    """Update reminder properties (title, due_date, priority, description, recurrence)."""
    graph = request.app.state.retrieval.graph
    result = await graph.update_reminder(
        title=req.title,
        new_title=req.new_title,
        due_date=req.due_date,
        priority=req.priority,
        description=req.description,
        recurrence=req.recurrence,
    )
    return result


@router.post("/delete")
async def delete_reminder(req: ReminderDeleteRequest, request: Request):
    """Delete reminder(s) by title, node ID, or status."""
    graph = request.app.state.retrieval.graph
    if req.node_id is not None:
        return await graph.delete_reminder_by_id(req.node_id)
    if req.title:
        return await graph.delete_reminder(req.title)
    if req.status:
        return await graph.delete_all_reminders(status=req.status)
    return {"error": "Provide title, node_id, or status to delete"}


@router.post("/delete-all")
async def delete_all_reminders(request: Request, status: str = ""):
    """Delete all reminders, optionally filtered by status query param."""
    graph = request.app.state.retrieval.graph
    return await graph.delete_all_reminders(status=status or None)


@router.post("/merge-duplicates")
async def merge_duplicate_reminders(request: Request):
    """Find and merge duplicate reminders. Keeps one per unique title."""
    graph = request.app.state.retrieval.graph
    return await graph.merge_duplicate_reminders()
