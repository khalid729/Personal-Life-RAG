import logging

from fastapi import APIRouter, Request

from app.models.schemas import IngestRequest, IngestResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/text", response_model=IngestResponse)
async def ingest_text(req: IngestRequest, request: Request):
    logger.info("Ingest text: %d chars, source=%s, preview: %s",
                len(req.text), req.source_type, req.text[:200])
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
        entities=result.get("entities", []),
    )
