# Architecture

## Overview

Personal Life RAG is a bilingual (Arabic/English) personal life management system. It combines a Knowledge Graph (FalkorDB), Vector Search (Qdrant), and an LLM (Qwen3-VL via vLLM) into an Agentic RAG pipeline that understands natural Arabic queries and manages finances, reminders, projects, tasks, knowledge, and more.

```
                      +------------------+
                      |   User (Arabic)  |
                      +--------+---------+
                               |
                      +--------v---------+
                      |   FastAPI :8500   |
                      |  (Routers Layer)  |
                      +--------+---------+
                               |
                 +-------------v--------------+
                 |     RetrievalService        |
                 |  (Agentic RAG Pipeline)     |
                 +--+------+------+------+----+
                    |      |      |      |
            +-------v+  +--v---+ +v-----+ +v---------+
            | LLM    |  |Graph | |Vector| | Memory   |
            | Service|  |Svc   | |Svc   | | Service  |
            +---+----+  +--+---+ +--+---+ +----+-----+
                |           |        |          |
            +---v----+  +---v---+ +--v----+ +---v-----+
            | vLLM   |  |Falkor | |Qdrant | | Redis   |
            | :8000  |  |DB     | | :6333 | | :6380   |
            |Qwen3-VL|  | :6379 | |BGE-M3 | | Memory  |
            +--------+  +-------+ +-------+ +---------+
```

## Services

### 1. LLM Service (`app/services/llm.py`)
- Connects to vLLM (OpenAI-compatible API) on port 8000
- Model: **Qwen3-VL-32B-Instruct** (90K context, vision-capable)
- Functions: translate (AR<>EN), extract facts, classify input, think/reflect (agentic), vision analysis, clarification checking, core memory extraction, daily summarization
- `enable_thinking: False` in chat_template_kwargs to avoid Qwen3 thinking tokens

### 2. Graph Service (`app/services/graph.py`)
- **FalkorDB** (Redis-based graph database) on port 6379
- Stores structured entities: Person, Company, Project, Task, Idea, Topic, Tag, Expense, Debt, Reminder, Knowledge, File
- Entity relationships via Cypher queries
- Dedicated query methods: financial summary/reports, debt management, reminders, daily planner, projects overview, knowledge search, active tasks
- `upsert_from_facts()` — auto-handles all entity types from LLM extraction
- Idea similarity detection: new ideas get embedded and linked via `SIMILAR_TO` edges

### 3. Vector Service (`app/services/vector.py`)
- **Qdrant** vector database on port 6333
- Embedding model: **BAAI/bge-m3** (1024-dim, loaded on GPU, ~3GB VRAM)
- Stores enriched text chunks with metadata
- Supports filtered search by source_type, entity_type, topic

### 4. Memory Service (`app/services/memory.py`)
- **Redis** (separate instance) on port 6380
- 3-layer memory architecture:
  - **Layer 1 — Working Memory**: last N message pairs (Redis List, 24h TTL)
  - **Layer 2 — Daily Summary**: compressed daily summary (7-day TTL)
  - **Layer 3 — Core Memory**: user preferences/patterns (permanent Redis Hash)
- Pending actions storage for confirmation flow (300s TTL)
- Message counter for triggering periodic tasks

### 5. File Service (`app/services/files.py`)
- Processes uploaded files: images, PDFs, audio
- Images: vLLM Vision API (classify type, then type-specific analysis)
- PDFs: pymupdf4llm for markdown extraction
- Audio: WhisperX (large-v3-turbo, loaded on-demand, serialized via asyncio.Lock)
- Files stored at `data/files/{hash[:2]}/{hash}.{ext}`
- Auto-expense: invoice images with total > 0 auto-create Expense nodes

### 6. Retrieval Service (`app/services/retrieval.py`)
- Orchestrates the full Agentic RAG pipeline (see [Pipeline](#agentic-rag-pipeline))
- Smart keyword router for zero-latency routing
- Ingestion pipeline: translate > chunk > enrich > embed + extract facts
- Post-processing: fact extraction, periodic summaries, core memory extraction

## Agentic RAG Pipeline

```
User Query (Arabic)
      |
      v
[Confirmation Pre-check] -- pending action? --> yes/no/number --> execute/cancel/disambiguate
      |
      v
[1. Translate AR -> EN]
      |
      v
[2. Smart Router (keywords)] -- match? --> fast path (skip Think)
      |                                         |
      v (no match)                              |
[3. THINK - LLM decides strategy]              |
      |                                         |
      v  <--------------------------------------+
[Confirmation Gate] -- side-effect + action? --> store pending, return confirmation message
      |
      v
[4. ACT - Execute retrieval strategy]
      |   graph_* routes: FalkorDB queries + hybrid vector search
      |   vector: Qdrant semantic search + graph fallback
      |   hybrid: both graph + vector
      |
      v
[5. REFLECT + Self-RAG] -- score chunks, filter below threshold (0.3)
      |
      v (if !sufficient)
[6. RETRY] -- flip strategy, merge results (max 1 retry)
      |
      v
[7. Build Context] -- system memory + conversation turns + filtered chunks (<=15K tokens)
      |
      v
[8. Generate Response] -- multi-turn Arabic response
      |
      v
[9. Post-process (background)] -- fact extraction, memory updates, periodic tasks
```

## Smart Router

Zero-latency keyword-based routing, checked in specificity order:

| Priority | Route | Triggers (AR/EN) |
|----------|-------|-------------------|
| 1 | `graph_debt_payment` | سدد، رجع الفلوس، paid back |
| 2 | `graph_debt_summary` | ديون، يطلبني، who owe |
| 3 | `graph_financial_report` | ملخص، تقرير، monthly spend |
| 4 | `graph_financial` | صرفت، دفعت، مصاريف |
| 5 | `graph_reminder_action` | خلصت + تذكير، done + reminder |
| 6 | `graph_reminder` | ذكرني، موعد، remind |
| 7 | `graph_daily_plan` | رتب يومي، خطة اليوم، plan my day |
| 8 | `graph_knowledge` | وش أعرف، معلومة، what do I know |
| 9 | `graph_project` | مشروع، project، progress |
| 10 | `graph_person` | مين، who، person |
| 11 | `graph_task` | مهمة، مهام، task، todo |
| 12 | `llm_classify` | fallback to LLM classification |

## Data Flow: Ingestion

```
Text/File Upload
      |
      v
[Translate AR -> EN]
      |
      +---> [Chunk text (500 tokens, 50 overlap)]
      |         |
      |         v
      |     [Contextual Enrichment (LLM adds doc context per chunk)]
      |         |
      |         v
      |     [Embed via BGE-M3 -> Qdrant]
      |
      +---> [Extract Facts (LLM)]
                |
                v
            [Upsert to FalkorDB (entities + relationships)]
```

## Configuration

All settings are in `app/config.py` via Pydantic `BaseSettings` (overridable via `.env`):

| Setting | Default | Description |
|---------|---------|-------------|
| `vllm_base_url` | `http://localhost:8000/v1` | vLLM API endpoint |
| `vllm_model` | `Qwen/Qwen3-VL-32B-Instruct` | LLM model name |
| `falkordb_port` | 6379 | FalkorDB port |
| `qdrant_port` | 6333 | Qdrant port |
| `redis_port` | 6380 | Redis memory port |
| `bge_model_name` | `BAAI/bge-m3` | Embedding model |
| `bge_device` | `cuda` | Embedding device |
| `bge_dimension` | 1024 | Embedding dimension |
| `api_port` | 8500 | FastAPI port |
| `working_memory_size` | 5 | Message pairs in working memory |
| `max_context_tokens` | 15000 | Token budget for LLM context |
| `self_rag_threshold` | 0.3 | Minimum chunk relevance score |
| `agentic_max_retries` | 1 | Max retrieval retries |
| `confirmation_enabled` | True | Enable confirmation flow |
| `confirmation_ttl_seconds` | 300 | Pending action TTL |
| `daily_summary_interval` | 10 | Messages between daily summaries |
| `core_memory_interval` | 20 | Messages between core memory extraction |
