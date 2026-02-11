"""Productivity endpoints — sprints, focus sessions, time-blocking."""

from fastapi import APIRouter, Request

from app.models.schemas import (
    FocusCompleteRequest,
    FocusStartRequest,
    FocusStatsResponse,
    SprintCreateRequest,
    SprintUpdateRequest,
    TimeBlockRequest,
    TimeBlockResponse,
)

router = APIRouter(prefix="/productivity", tags=["productivity"])


# --- Sprints ---


@router.post("/sprints/")
async def create_sprint(req: SprintCreateRequest, request: Request):
    graph = request.app.state.retrieval.graph
    result = await graph.create_sprint(
        req.name,
        start_date=req.start_date,
        end_date=req.end_date,
        goal=req.goal,
        project=req.project,
    )
    return result


@router.get("/sprints/")
async def list_sprints(request: Request, status: str | None = None):
    graph = request.app.state.retrieval.graph
    sprints = await graph.query_sprints(status_filter=status)
    return {"sprints": sprints}


@router.get("/sprints/{name}/burndown")
async def sprint_burndown(name: str, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.query_sprint_burndown(name)


@router.post("/sprints/{name}/complete")
async def complete_sprint(name: str, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.complete_sprint(name)


@router.get("/sprints/velocity")
async def sprint_velocity(request: Request, project: str | None = None):
    graph = request.app.state.retrieval.graph
    return await graph.query_sprint_velocity(project)


@router.post("/sprints/{sprint}/tasks/{task}")
async def assign_task_to_sprint(sprint: str, task: str, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.assign_task_to_sprint(task, sprint)


# --- Focus Sessions ---


@router.post("/focus/start")
async def start_focus(req: FocusStartRequest, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.start_focus_session(
        duration_minutes=req.duration_minutes,
        task_title=req.task,
    )


@router.post("/focus/complete")
async def complete_focus(req: FocusCompleteRequest, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.complete_focus_session(completed=req.completed)


@router.get("/focus/stats")
async def focus_stats(request: Request):
    graph = request.app.state.retrieval.graph
    stats = await graph.query_focus_stats()
    return FocusStatsResponse(**stats)


# --- Time-Blocking ---


@router.post("/timeblock/suggest")
async def suggest_time_blocks(req: TimeBlockRequest, request: Request):
    graph = request.app.state.retrieval.graph
    result = await graph.suggest_time_blocks(req.date, req.energy_override)
    return TimeBlockResponse(**result)


@router.post("/timeblock/apply")
async def apply_time_blocks(req: TimeBlockResponse, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.apply_time_blocks(req.blocks, req.date)
