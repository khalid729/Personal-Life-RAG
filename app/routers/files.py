import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.models.schemas import FileUploadResponse, IngestResponse, URLIngestRequest

logger = logging.getLogger(__name__)

settings = get_settings()

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/file", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile,
    context: str = Form(""),
    tags: str = Form(""),
    topic: str = Form(""),
):
    file_service = request.app.state.file_service

    # Validate file size
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.max_file_size_mb}MB",
        )

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # Parse tags from comma-separated string
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    result = await file_service.process_file(
        file_bytes=file_bytes,
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        user_context=context,
        tags=tag_list,
        topic=topic or None,
    )

    return FileUploadResponse(**result)


@router.post("/url", response_model=IngestResponse)
async def ingest_url(req: URLIngestRequest, request: Request):
    file_service = request.app.state.file_service
    result = await file_service.process_url(
        url=req.url,
        user_context=req.context,
        tags=req.tags,
        topic=req.topic,
    )
    return IngestResponse(
        status=result["status"],
        chunks_stored=result["chunks_stored"],
        facts_extracted=result["facts_extracted"],
        entities=result.get("entities", []),
    )


@router.get("/file/{file_hash}")
async def download_file(request: Request, file_hash: str):
    graph = request.app.state.graph_service
    file_info = await graph.find_file_by_hash(file_hash)
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")

    props = file_info.get("properties", {})
    original_name = props.get("filename", "download")

    storage = Path(settings.file_storage_path) / file_hash[:2]
    matches = list(storage.glob(f"{file_hash}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_path = matches[0]
    return FileResponse(
        path=str(file_path),
        filename=original_name,
        media_type="application/octet-stream",
    )
