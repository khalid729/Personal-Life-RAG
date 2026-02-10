import logging

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from app.config import get_settings
from app.models.schemas import FileUploadResponse

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
