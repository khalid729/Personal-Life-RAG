from fastapi import APIRouter, Request

from app.models.schemas import TaskDeleteRequest, TaskUpdateRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/")
async def list_tasks(request: Request, status: str | None = None):
    graph = request.app.state.retrieval.graph
    text = await graph.query_active_tasks(status_filter=status)
    return {"tasks": text}


@router.post("/update")
async def update_task(req: TaskUpdateRequest, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.update_task_direct(
        title=req.title,
        new_title=req.new_title,
        status=req.status,
        due_date=req.due_date,
        priority=req.priority,
        project=req.project,
    )


@router.post("/delete")
async def delete_task(req: TaskDeleteRequest, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.delete_task(req.title)


@router.post("/merge-duplicates")
async def merge_duplicate_tasks(request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.merge_duplicate_tasks()
