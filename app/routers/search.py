from fastapi import APIRouter, Request

from app.models.schemas import SearchRequest, SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request):
    retrieval = request.app.state.retrieval

    result = await retrieval.search_direct(
        query=req.query,
        source=req.source,
        limit=req.limit,
    )

    return SearchResponse(
        results=[
            SearchResult(
                text=r["text"],
                score=r["score"],
                source=r["source"],
                metadata=r.get("metadata", {}),
            )
            for r in result["results"]
        ],
        source_used=result["source_used"],
    )
