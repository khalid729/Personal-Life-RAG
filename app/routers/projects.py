from fastapi import APIRouter, Request

from app.models.schemas import ProjectUpdateRequest

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/")
async def projects_overview(request: Request, status: str | None = None):
    graph = request.app.state.retrieval.graph
    text = await graph.query_projects_overview(status_filter=status)
    return {"projects": text}


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
