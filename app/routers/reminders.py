from fastapi import APIRouter, Request

from app.models.schemas import ReminderActionRequest

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
