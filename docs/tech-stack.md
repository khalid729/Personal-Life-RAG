# Tech Stack

## Core Infrastructure

| Tool | Version | Role | Port |
|------|---------|------|------|
| **FastAPI** | >= 0.115.0 | API framework, async request handling | 8500 |
| **Uvicorn** | >= 0.34.0 | ASGI server with hot-reload | 8500 |
| **vLLM** | external | LLM inference server (OpenAI-compatible API) | 8000 |
| **FalkorDB** | external (Docker) | Graph database (Redis-based, Cypher queries) | 6379 |
| **Qdrant** | external (Docker) | Vector database (cosine similarity search) | 6333 |
| **Redis** | external (Docker) | Working memory, session state, pending actions | 6380 |

## AI Models

| Model | Purpose | Details |
|-------|---------|---------|
| **Qwen3-VL-32B-Instruct** | LLM (text + vision) | 90K context, served via vLLM, supports Arabic |
| **BAAI/bge-m3** | Text embeddings | 1024-dim, loaded on GPU (~3GB VRAM), multilingual |
| **WhisperX large-v3-turbo** | Speech-to-text | Loaded on-demand, float16, serialized via asyncio.Lock |

## Python Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | >= 0.115.0 | Web framework |
| `uvicorn[standard]` | >= 0.34.0 | ASGI server |
| `httpx` | >= 0.28.0 | Async HTTP client (vLLM API calls) |
| `falkordb` | >= 1.0.0 | FalkorDB async client |
| `qdrant-client` | >= 1.12.0 | Qdrant async client |
| `redis` | >= 5.0.0 | Redis async client (memory service) |
| `sentence-transformers` | >= 3.3.0 | BGE-M3 embedding model |
| `pydantic-settings` | >= 2.7.0 | Configuration management |
| `python-multipart` | >= 0.0.18 | File upload handling |
| `tiktoken` | >= 0.8.0 | Token counting for context budget |
| `pymupdf4llm` | >= 0.0.17 | PDF to markdown extraction |
| `aiofiles` | >= 24.1.0 | Async file I/O |
| `aiogram` | >= 3.15.0 | Telegram Bot framework (async, aiogram 3.x) |
| `fastmcp` | >= 2.0.0 | MCP server framework (SSE transport) |
| `apscheduler` | >= 3.10.0 | Scheduled jobs (proactive notifications) |
| `python-dateutil` | >= 2.9.0 | Recurring reminder date advancement (relativedelta) |

## Why These Choices

### vLLM + Qwen3-VL
- Self-hosted LLM for privacy (personal data never leaves the machine)
- Qwen3-VL supports Arabic natively + vision capabilities (invoice scanning)
- 90K context window handles large document chunks
- OpenAI-compatible API makes it a drop-in replacement

### FalkorDB (Graph)
- Redis-based = fast, lightweight, no separate JVM/cluster
- Cypher query language for relationship traversal
- Perfect for structured personal data (people, debts, projects, etc.)
- 2-hop queries for rich context (person -> project -> tasks)

### Qdrant (Vector)
- Purpose-built vector DB with filtering support
- Payload-based filtering (source_type, entity_type) without separate indexes
- Async client with gRPC support

### BGE-M3
- Multilingual embeddings (Arabic + English in same space)
- 1024-dim = good balance of quality vs storage
- Runs on GPU for fast embedding (~3GB VRAM)

### Redis (Memory)
- Separate instance from FalkorDB to avoid interference
- List + Hash + String types map naturally to 3-layer memory
- TTL for automatic cleanup of stale data

### WhisperX
- Better than vanilla Whisper: word-level timestamps, speaker diarization
- Loaded on-demand to save GPU memory when not in use
- Serialized via asyncio.Lock to prevent concurrent GPU access

## Interfaces

| Tool | Version | Role | Port |
|------|---------|------|------|
| **aiogram** | >= 3.15.0 | Telegram Bot (text, voice, photo, documents) | — (polling) |
| **FastMCP** | >= 2.0.0 | MCP server for Claude Desktop (SSE transport) | 8600 |
| **Open WebUI** | external (Docker) | Browser chat interface with custom tools | 3000→8080 |

## System Requirements

- **GPU**: NVIDIA GPU with >= 24GB VRAM (for vLLM + BGE-M3 + WhisperX)
- **RAM**: >= 32GB recommended
- **Docker**: For FalkorDB, Qdrant, Redis containers
- **Python**: 3.12+
