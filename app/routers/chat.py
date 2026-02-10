from fastapi import APIRouter, BackgroundTasks, Request

from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks, request: Request):
    retrieval = request.app.state.retrieval

    result = await retrieval.retrieve_and_respond(
        query_ar=req.message,
        session_id=req.session_id,
    )

    # Post-processing in background (memory update, fact extraction, embeddings)
    background_tasks.add_task(
        retrieval.post_process,
        req.message,
        result["reply"],
        req.session_id,
    )

    return ChatResponse(
        reply=result["reply"],
        sources=result.get("sources", []),
        route=result.get("route"),
        agentic_trace=result.get("agentic_trace", []),
    )
