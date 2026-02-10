from fastapi import APIRouter, Request

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/")
async def list_tasks(request: Request, status: str | None = None):
    graph = request.app.state.retrieval.graph
    text = await graph.query_active_tasks(status_filter=status)
    return {"tasks": text}
