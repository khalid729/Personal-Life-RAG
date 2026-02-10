# Project Structure

```
Personal_Rag/
├── app/
│   ├── main.py                  # FastAPI app, lifespan (service init/teardown), router wiring
│   ├── config.py                # Pydantic Settings (all ports, models, thresholds, overridable via .env)
│   │
│   ├── models/
│   │   └── schemas.py           # Pydantic models: enums, entity schemas, API request/response models
│   │
│   ├── services/
│   │   ├── llm.py               # vLLM client — translate, extract, classify, vision, think/reflect,
│   │   │                        #   clarification, core memory extraction, daily summarization
│   │   ├── graph.py             # FalkorDB — entity CRUD, entity resolution (vector dedup),
│   │   │                        #   smart tags (normalization + TAGGED_WITH), knowledge auto-categorization,
│   │   │                        #   multi-hop traversal (3-hop), financial reports, debt management,
│   │   │                        #   reminders, daily planner, projects overview, knowledge queries,
│   │   │                        #   active tasks, idea similarity, inventory (items, locations, movement,
│   │   │                        #   barcode lookup, last-use tracking, reports, duplicate detection)
│   │   ├── vector.py            # Qdrant — BGE-M3 embedding, chunk upsert/search with filtering
│   │   ├── memory.py            # Redis — 3-layer memory (working/daily/core), pending actions,
│   │   │                        #   message counter, context builders
│   │   ├── retrieval.py         # Agentic RAG pipeline — smart router, ingestion, retrieval
│   │   │                        #   (think/act/reflect/retry), confirmation flow, post-processing
│   │   └── files.py             # File processing — images (vision), PDFs (pymupdf4llm),
│   │                            #   audio (WhisperX), auto-expense, auto-item from photos,
│   │                            #   barcode scanning (pyzbar)
│   │
│   ├── routers/
│   │   ├── chat.py              # POST /chat/ — main conversational endpoint
│   │   ├── ingest.py            # POST /ingest/text — text ingestion
│   │   ├── files.py             # POST /ingest/file — file upload + processing
│   │   ├── search.py            # POST /search/ — direct search (vector/graph/auto)
│   │   ├── financial.py         # GET /financial/report, /debts, /alerts + POST /debts/payment
│   │   ├── reminders.py         # GET /reminders/ + POST /reminders/action
│   │   ├── projects.py          # GET /projects/ + POST /projects/update
│   │   ├── tasks.py             # GET /tasks/
│   │   ├── knowledge.py         # GET /knowledge/
│   │   ├── inventory.py         # GET/POST /inventory/* (items, summary, location, quantity, search-similar,
│   │   │                        #   report, unused, duplicates, by-barcode)
│   │   └── proactive.py         # GET/POST /proactive/* (morning, noon, evening, reminders, alerts)
│   │
│   ├── prompts/
│   │   ├── translate.py         # Arabic<>English translation prompts
│   │   ├── classify.py          # Input category classification prompt
│   │   ├── extract.py           # Fact/entity extraction prompt (incl. DebtPayment, ItemUsage, ItemMove)
│   │   ├── file_classify.py     # Image file type classification prompt
│   │   ├── vision.py            # Type-specific image analysis prompts (invoice, document, etc.)
│   │   ├── agentic.py           # Think + Reflect prompts for agentic RAG pipeline
│   │   └── conversation.py      # Confirmation, clarification, action detection (Phase 4)
│   │
│   └── integrations/            # External interfaces (Phase 5)
│       ├── __init__.py
│       ├── telegram_bot.py      # Telegram bot (aiogram 3.x, standalone process)
│       └── openwebui_tools.py   # Open WebUI tools file (copy to WebUI Admin)
│
├── data/
│   └── files/                   # Uploaded files (content-addressed: {hash[:2]}/{hash}.{ext})
│
├── docs/                        # Documentation
│   ├── architecture.md          # System architecture and data flow
│   ├── tech-stack.md            # Tools, models, and dependencies
│   ├── api.md                   # API endpoint reference
│   ├── progress.md              # Completed phases and remaining work
│   └── project-structure.md     # This file
│
├── mcp_server.py                # MCP server (FastMCP, SSE on port 8600)
├── requirements.txt             # Python dependencies
├── .env                         # Environment overrides (optional)
│
└── scripts/
    ├── start.sh                 # Start RAG API
    ├── start_telegram.sh        # Start Telegram bot
    ├── start_mcp.sh             # Start MCP server
    ├── setup_graph.py           # FalkorDB schema setup
    └── test_services.py         # Service connectivity tests
```

## Key Design Patterns

### Async Everything
All services use async clients: `httpx.AsyncClient`, `falkordb.asyncio`, `AsyncQdrantClient`, `redis.asyncio`. This ensures the FastAPI event loop is never blocked.

### Service Initialization via Lifespan
Services are created and started in `main.py`'s `lifespan` context manager, stored on `app.state`, and cleaned up on shutdown. Routers access services via `request.app.state.retrieval`.

### Background Post-Processing
After each chat response, `post_process()` runs in a FastAPI `BackgroundTask`:
- Stores the exchange in working memory
- Extracts facts from user query (preserves intent) and combined exchange (captures relationships)
- Dedup: combined extraction skips entity types already found in query extraction
- Periodically triggers daily summaries and core memory extraction

### Confirmation Flow
Side-effect routes (expense, debt, reminder) go through a confirmation gate:
1. Extract entities from the query
2. Check if enough info (clarification if not)
3. Build confirmation message, store pending action in Redis (300s TTL)
4. User confirms (yes/no) → execute or cancel
5. Disambiguation if multiple matches (e.g. multiple debts with same person)
