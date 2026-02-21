from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.models.schemas import ProjectDeleteRequest, ProjectMergeRequest, ProjectUpdateRequest

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/")
async def projects_overview(request: Request, status: str | None = None):
    graph = request.app.state.retrieval.graph
    text = await graph.query_projects_overview(status_filter=status)
    return {"projects": text}


@router.get("/details")
async def project_details(request: Request, name: str):
    graph = request.app.state.retrieval.graph
    text = await graph.query_project_details(name)
    return {"details": text}


class FocusRequest(BaseModel):
    name: str
    session_id: str = "claude-desktop"


@router.post("/focus")
async def focus_project(req: FocusRequest, request: Request):
    graph = request.app.state.retrieval.graph
    memory = request.app.state.memory
    resolved = await graph.resolve_entity_name(req.name, "Project")
    # Verify project exists
    rows = await graph.query(
        "MATCH (p:Project) WHERE toLower(p.name) CONTAINS toLower($n) RETURN p.name LIMIT 1",
        {"n": resolved},
    )
    if not rows:
        return {"error": f"No project found matching '{req.name}'"}
    project_name = rows[0][0]
    await memory.set_active_project(req.session_id, project_name)
    return {"status": "focused", "project": project_name}


@router.post("/unfocus")
async def unfocus_project(request: Request, session_id: str = "claude-desktop"):
    memory = request.app.state.memory
    await memory.clear_active_project(session_id)
    return {"status": "unfocused"}


@router.post("/update")
async def update_project(req: ProjectUpdateRequest, request: Request):
    graph = request.app.state.retrieval.graph
    props = {}
    if req.status is not None:
        props["status"] = req.status
    if req.description is not None:
        props["description"] = req.description
    if req.priority is not None:
        props["priority"] = req.priority
    await graph.upsert_project(req.name, **props)
    return {"status": "ok", "project": req.name}


@router.post("/delete")
async def delete_project(req: ProjectDeleteRequest, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.delete_project(req.name)


@router.post("/merge")
async def merge_projects(req: ProjectMergeRequest, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.merge_projects(req.sources, req.target)
