import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/v2", response_model=ChatResponse)
async def chat_v2(req: ChatRequest, request: Request):
    """Tool-calling chat endpoint. Model calls tools, code executes, model formats result."""
    tool_calling = request.app.state.tool_calling

    result = await tool_calling.chat(
        message=req.message,
        session_id=req.session_id,
    )

    # post_process is called inside tool_calling.chat() via asyncio.create_task

    return ChatResponse(
        reply=result["reply"],
        sources=[],
        route=result.get("route"),
        agentic_trace=[{"step": "tool_calls", "tools": result.get("tool_calls", [])}],
        tool_calls=result.get("tool_calls", []),
    )


@router.post("/v2/stream")
async def chat_v2_stream(req: ChatRequest, request: Request):
    """Streaming tool-calling endpoint. Tool execution is non-streaming, final response streams."""
    tool_calling = request.app.state.tool_calling

    async def event_generator():
        async for line in tool_calling.chat_stream(req.message, req.session_id):
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
