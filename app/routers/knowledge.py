from fastapi import APIRouter, Request

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/")
async def list_knowledge(request: Request, topic: str | None = None):
    graph = request.app.state.retrieval.graph
    text = await graph.query_knowledge(topic=topic)
    return {"knowledge": text}
