# Services

8 async services, all with `start()` / `stop()` lifecycle. Injected via `app.state` in main.py lifespan.

## Service Map

| Service | File | Size | Backend |
|---------|------|------|---------|
| LLMService | llm.py | 13KB | vLLM :8000 via httpx.AsyncClient |
| GraphService | graph.py | 110KB | FalkorDB :6379 via falkordb.asyncio |
| VectorService | vector.py | 4KB | Qdrant :6333 + BGE-M3 on GPU |
| MemoryService | memory.py | 7KB | Redis :6380 (3 layers) |
| RetrievalService | retrieval.py | 49KB | Orchestrates all above |
| FileService | files.py | 25KB | Image/PDF/audio processing |
| BackupService | backup.py | 13KB | Timestamped graph+vector+redis snapshots |
| NERService | ner.py | 3KB | CAMeL-Lab Arabic BERT NER |

## Dependency Graph

```
RetrievalService(llm, graph, vector, memory, ner)
FileService(llm, retrieval)
BackupService(graph, vector, memory)
GraphService.set_vector_service(vector)  # for entity resolution
```

## GraphService (graph.py) — Largest file

- 15+ entity types: Person, Company, Project, Task, Expense, Debt, DebtPayment, Reminder, Knowledge, Topic, Tag, Item, Sprint, FocusSession, File
- Entity resolution: `resolve_entity_name(name, label)` → vector similarity → canonical name
- `query_person_context(query)`: fuzzy name matching — extracts candidate names, CONTAINS search, returns all matches + fallback summary of all persons
- `upsert_person()`: auto-converts Hijri dates (year < 1900) to Gregorian via `hijri-converter`; stores `date_of_birth` (gregorian) + `date_of_birth_hijri`
- Person nodes support `name_ar` property for Arabic name preservation
- `_INTERNAL_PROPS`: filtered from LLM context (`name_aliases`, `created_at`, `updated_at`, `file_hash`, `source`)
- `_build_set_clause(props, var)`: generates Cypher SET from dict; skips empty strings to prevent overwriting good data
- `_format_graph_context()` / `_format_graph_context_3hop()`: format multi-hop query results for LLM
- `upsert_from_facts(entities)`: main ingestion — routes each entity_type to its upsert method
- `find_file_by_hash(hash)`: check File node existence

### FalkorDB Gotchas
- `GRAPH.CONSTRAINT CREATE` for unique constraints (not Cypher syntax)
- `result.result_set` returns rows as lists, nodes have `.properties` dict
- `r.key = $val` only valid in SET clauses, NOT in `CREATE ({...})`
- Only primitive types or arrays of primitives — convert dict→str, list[dict]→list[str]
- Async: `from falkordb.asyncio import FalkorDB` + `BlockingConnectionPool` from redis.asyncio

## RetrievalService (retrieval.py) — Core RAG Logic

- **Smart routing**: 20 keyword patterns in specificity order, fallback to LLM classify
- **Pipeline**: Think (pick strategy) → Act (execute graph/vector queries) → Reflect (score chunks, filter < 0.3)
- **Retry**: if reflect says insufficient, retry with broader strategy
- **Post-processing**: BackgroundTasks runs `_extract_and_upsert()` — extracts from query alone + combined exchange
- **Dedup**: combined extraction skips entity types already found in query extraction
- **Confirmation flow**: only for delete/cancel intents
- **Clarification**: skipped if extraction found named entities

## FileService (files.py)

- `process_file()`: classify → extract/analyze → ingest text + store file
- Image: classify type → vision analysis → `_analysis_to_text()` → ingest
- PDF: pymupdf4llm extract; if <200 chars → `_pdf_to_vision()` (render pages → Qwen2.5-VL)
- Audio: WhisperX transcription (lazy-loaded, GPU, Arabic)
- Barcode: `_scan_barcodes()` via pyzbar
- `_save_file()`: stores at `data/files/{hash[:2]}/{hash}.{ext}`
- `_analysis_to_text()`: converts structured JSON to readable text per file_type

## MemoryService (memory.py)

3-layer Redis memory:
- **Working**: last N messages (FIFO list, LTRIM)
- **Daily summary**: compressed daily summary (TTL: 7 days)
- **Core**: preferences and patterns (permanent Hash)

## VectorService (vector.py)

- BGE-M3 model on GPU (1024-dim, ~3GB VRAM)
- `embed(text)` → numpy array
- `upsert(id, text, metadata)` → Qdrant point
- `search(query, limit, filters)` → scored results

## BackupService (backup.py)

- `create_backup()` → `data/backups/{timestamp}/` with graph.json, vector.json, redis.json
- `restore_backup(timestamp)` → MERGE nodes/edges, upsert Qdrant, SET/RPUSH/HSET Redis
- Daily job at `backup_hour` (3 AM), retention `backup_retention_days` (30)

## NERService (ner.py)

- Lazy-loaded `transformers` pipeline with `CAMeL-Lab/bert-base-arabic-camelbert-msa-ner`
- Extracts Person, Location, Organization (score ≥ 0.7)
- Results prepended as `[NER hints: Person: محمد; Location: الرياض]` to extract prompt
