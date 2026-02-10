from fastapi import APIRouter, Request

from app.models.schemas import IngestRequest, IngestResponse

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/text", response_model=IngestResponse)
async def ingest_text(req: IngestRequest, request: Request):
    retrieval = request.app.state.retrieval

    result = await retrieval.ingest_text(
        text=req.text,
        source_type=req.source_type,
        tags=req.tags,
        topic=req.topic,
    )

    return IngestResponse(
        status="ok",
        chunks_stored=result["chunks_stored"],
        facts_extracted=result["facts_extracted"],
    )
