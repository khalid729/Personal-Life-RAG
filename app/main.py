import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routers import chat, files, financial, ingest, inventory, knowledge, proactive, productivity, projects, reminders, search, tasks
from app.routers import backup as backup_router
from app.routers import graph_viz
from app.services.backup import BackupService
from app.services.files import FileService
from app.services.graph import GraphService
from app.services.llm import LLMService
from app.services.memory import MemoryService
from app.services.ner import NERService
from app.services.retrieval import RetrievalService
from app.services.vector import VectorService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Starting services...")

    llm = LLMService()
    graph = GraphService()
    vector = VectorService()
    memory = MemoryService()
    ner = NERService()

    await llm.start()
    logger.info("LLM service ready")

    await graph.start()
    logger.info("Graph service ready")

    await vector.start()
    logger.info("Vector service ready")

    await memory.start()
    logger.info("Memory service ready")

    await ner.start()
    logger.info("NER service ready")

    graph.set_vector_service(vector)

    retrieval = RetrievalService(llm, graph, vector, memory, ner=ner)
    app.state.retrieval = retrieval

    file_service = FileService(llm, retrieval)
    app.state.file_service = file_service

    backup_service = BackupService(graph, vector, memory)
    app.state.backup_service = backup_service

    logger.info("All services started. API is ready.")
    yield

    # --- Shutdown ---
    logger.info("Shutting down services...")
    await memory.stop()
    await vector.stop()
    await graph.stop()
    await llm.stop()
    logger.info("All services stopped.")


app = FastAPI(
    title="Personal Life RAG",
    description="Personal life management system with Contextual Retrieval",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(files.router)
app.include_router(search.router)
app.include_router(financial.router)
app.include_router(reminders.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(knowledge.router)
app.include_router(proactive.router)
app.include_router(inventory.router)
app.include_router(productivity.router)
app.include_router(backup_router.router)
app.include_router(graph_viz.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/debug/filter-inlet")
async def debug_filter_inlet(request: Request):
    """Debug endpoint: receives full body from Open WebUI filter to inspect structure."""
    import json
    body = await request.json()

    # Write to file for inspection
    debug_path = "data/debug_filter_body.json"
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2, default=str)

    # Log summary
    messages = body.get("messages", [])
    logger.info("=== FILTER DEBUG: %d messages ===", len(messages))
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        content_type = type(content).__name__
        content_len = len(str(content))
        # Check for files/images in message
        has_files = "files" in msg
        has_images = "images" in msg
        logger.info("  msg[%d] role=%s content_type=%s len=%d files=%s images=%s",
                     i, role, content_type, content_len, has_files, has_images)
        # Log first 200 chars of content
        preview = str(content)[:200]
        logger.info("  msg[%d] preview: %s", i, preview)

    # Log body-level keys
    body_keys = [k for k in body.keys() if k != "messages"]
    logger.info("  body keys (non-messages): %s", body_keys)
    for k in body_keys:
        v = body[k]
        logger.info("  body[%s] type=%s preview=%s", k, type(v).__name__, str(v)[:200])

    return {"status": "ok", "messages_count": len(messages), "body_keys": body_keys}
