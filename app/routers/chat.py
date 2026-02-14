from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks, request: Request):
    retrieval = request.app.state.retrieval

    result = await retrieval.retrieve_and_respond(
        query_ar=req.message,
        session_id=req.session_id,
    )

    pending_confirmation = result.get("pending_confirmation", False)

    # Post-processing in background (memory update, vector embeddings)
    # Fact extraction now happens in the main pipeline (Stage 2)
    background_tasks.add_task(
        retrieval.post_process,
        req.message,
        result["reply"],
        req.session_id,
        query_en=result.get("query_en"),
        skip_fact_extraction=pending_confirmation or req.skip_fact_extraction,
    )

    return ChatResponse(
        reply=result["reply"],
        sources=result.get("sources", []),
        route=result.get("route"),
        agentic_trace=result.get("agentic_trace", []),
        pending_confirmation=pending_confirmation,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """Streaming chat endpoint — returns NDJSON lines."""
    retrieval = request.app.state.retrieval

    async def event_generator():
        async for line in retrieval.retrieve_and_respond_stream(
            req.message, req.session_id
        ):
            yield line

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@router.get("/summary")
async def chat_summary(session_id: str, request: Request):
    """Force-summarize current conversation and return summary."""
    retrieval = request.app.state.retrieval
    memory = retrieval.memory

    messages = await memory.get_working_memory(session_id)
    if not messages:
        return {"summary": "", "message_count": 0}

    # Check for existing summary
    existing = await memory.get_conversation_summary(session_id)

    # Force-generate a new summary from current messages
    summary = await retrieval.llm.summarize_conversation(messages)
    await memory.save_conversation_summary(session_id, summary)

    return {
        "summary": summary,
        "message_count": len(messages),
        "previous_summary": existing,
    }
