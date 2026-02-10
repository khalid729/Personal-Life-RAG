# Progress Tracker

## Completed Phases

### Phase 1 — Core RAG System
- [x] FastAPI app with lifespan startup/shutdown
- [x] vLLM integration (Qwen3-VL-32B-Instruct)
- [x] FalkorDB graph service (entities: Person, Company, Project, Task, Idea, Topic, Tag)
- [x] Qdrant vector service (BGE-M3 embeddings, 1024-dim)
- [x] Redis 3-layer memory (working, daily summary, core)
- [x] Arabic<>English translation via LLM
- [x] Text ingestion pipeline (translate > chunk > enrich > embed + extract facts)
- [x] Contextual Retrieval (LLM adds document context to each chunk)
- [x] Fact extraction and graph upsert
- [x] Basic chat endpoint with RAG response generation
- [x] Search endpoint (vector/graph/auto)
- [x] Text ingestion endpoint

### Phase 2 — Agentic RAG + File Processing
- [x] Think > Act > Reflect pipeline with Self-RAG chunk scoring
- [x] Smart keyword router (zero-latency fast path)
- [x] Max 1 retry (flip strategy if Reflect says insufficient)
- [x] Image processing (vLLM Vision: classify type > analyze)
- [x] PDF processing (pymupdf4llm markdown extraction)
- [x] Audio processing (WhisperX on-demand, serialized via Lock)
- [x] File storage (content-addressed: `data/files/{hash[:2]}/{hash}.{ext}`)
- [x] File node in graph + relationships
- [x] Agentic trace in ChatResponse for observability

### Phase 3 — Financial System + Smart Reminders
- [x] Expense tracking (create, category breakdown, monthly reports)
- [x] Debt management (upsert, payment recording, partial status, disambiguation)
- [x] Spending alerts (40% above 3-month average)
- [x] Month-over-month comparison
- [x] 5 reminder types (one_time, recurring, persistent, event_based, financial)
- [x] Reminder actions (done, snooze, cancel)
- [x] Finer-grained smart router (debt_payment > debt_summary > financial_report > financial)
- [x] DebtPayment pseudo-entity in extraction
- [x] Auto-expense from invoice images
- [x] Category guessing heuristic (keyword-based, no LLM)
- [x] REST endpoints: /financial/report, /debts, /debts/payment, /alerts, /reminders/, /reminders/action

### Phase 4a — Smarter Conversations
- [x] Confirmation flow for side-effect routes (financial, debt_payment, reminder)
- [x] Pending actions in Redis with 300s TTL
- [x] Action vs Query detection (heuristic pattern matching)
- [x] Disambiguation for multiple matching debts
- [x] Multi-turn conversation history (actual message turns, not flattened)
- [x] Token budget management (memory + history + context <= 15K)
- [x] Clarification prompts (missing required fields)
- [x] Periodic tasks: daily summary (every 10 msgs), core memory extraction (every 20 msgs)
- [x] Post-processing dedup (query extraction vs combined extraction)

### Phase 4b — Daily Planner, Projects, Knowledge, GraphRAG
- [x] Daily planner aggregation (reminders + tasks + debts I owe)
- [x] Projects overview with task progress (done/total)
- [x] Knowledge node querying with topic filter
- [x] Active tasks with project links and status filter
- [x] Idea similarity detection (vector search + SIMILAR_TO edges)
- [x] Smart router: `graph_daily_plan`, `graph_knowledge` keywords
- [x] Agentic prompts updated with new strategies
- [x] REST endpoints: /projects/, /projects/update, /tasks/, /knowledge/
- [x] `_build_set_clause` bug fix (variable name mismatch)

---

## Remaining / Future Ideas

### GraphRAG Enhancements
- [ ] Community detection (auto-cluster related entities)
- [ ] Multi-hop graph traversal in retrieval (not just 2-hop)
- [ ] Graph-based ranking (PageRank on entities for importance scoring)
- [ ] Entity resolution / dedup (merge "Mohammed" / "Mohamed" / "محمد")

### Daily Planner (ADHD Mode)
- [ ] Time-blocking suggestions based on task priorities
- [ ] Energy-level awareness (morning vs evening tasks)
- [ ] Pomodoro-style breakdowns for large tasks
- [ ] Push notifications / webhook integration

### Project Management
- [ ] Gantt-style timeline view
- [ ] Auto-link tasks to projects via LLM context
- [ ] Sprint/milestone tracking
- [ ] Progress percentage calculation

### Knowledge System
- [ ] Auto-tag knowledge entries by category
- [ ] Spaced repetition reminders for review
- [ ] Knowledge graph visualization
- [ ] Import from external sources (Notion, Obsidian)

### General Improvements
- [ ] Streaming responses (SSE)
- [ ] WebSocket real-time updates
- [ ] Frontend UI (web dashboard)
- [ ] User authentication (multi-user support)
- [ ] Backup/export (graph + vector snapshots)
- [ ] Recurring reminder execution (cron-like scheduler)
- [ ] Arabic NER improvement (custom patterns for Saudi names/places)
- [ ] Conversation summarization for long sessions
