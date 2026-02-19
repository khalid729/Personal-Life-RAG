# Services

8 async services with `start()`/`stop()` lifecycle, injected via `app.state`.

## Service Map

| Service | File | Backend |
|---------|------|---------|
| LLMService | llm.py | vLLM :8000 (httpx) |
| GraphService | graph.py (110KB) | FalkorDB :6379 |
| VectorService | vector.py | Qdrant :6333 + BGE-M3 GPU |
| MemoryService | memory.py | Redis :6380 (3 layers) |
| RetrievalService | retrieval.py | Ingestion + search (llm, graph, vector, memory) |
| ToolCallingService | tool_calling.py | Tool-calling chat orchestration |
| FileService | files.py | Image/PDF/audio processing |
| BackupService | backup.py | Timestamped snapshots |
| NERService | ner.py | CAMeL-Lab Arabic BERT NER |

## Dependencies

```
RetrievalService(llm, graph, vector, memory, ner)
ToolCallingService(llm, graph, vector, memory, ner)
FileService(llm, retrieval)
BackupService(graph, vector, memory)
GraphService.set_vector_service(vector)  # entity resolution
```

## GraphService (graph.py)

- 15+ entity types: Person, Company, Project, Task, Expense, Debt, Reminder, Knowledge, Item, Sprint, etc.
- `resolve_entity_name(name, label)`: vector similarity → graph CONTAINS fallback → canonical name
- `_resolve_by_graph_contains(name, type)`: substring match on `name` + `name_aliases` in graph
- `query_project_details(name)`: full project properties + linked tasks
- `upsert_person()`: auto Hijri→Gregorian for year < 1900
- `_display_name(props)`: `"رهف (Rahaf)"` if `name_ar` exists
- `_build_set_clause()`: skips empty strings
- `_format_graph_context()` / `_3hop()`: multi-hop results for LLM, uses `_display_name()`
- `query_projects_overview()`: case-insensitive status filter via `toLower()`
- `find_file_by_filename(name)`: latest File node by filename (for re-upload detection)
- `supersede_file(new_hash, old_hash)`: `(:File {new})-[:SUPERSEDES]->(:File {old})`
- `ensure_file_stub(hash, filename)`: creates minimal File node before ingestion so EXTRACTED_FROM links work
- `_link_entity_to_file(type, name, hash)`: `MERGE (e)-[:EXTRACTED_FROM]->(f:File)` — skips pseudo-entities
- `cleanup_file_entities(old_hash)`: deletes entities ONLY linked to old file (no other source); `DETACH DELETE`
- `_unlink_file_entities(hash)`: removes all `EXTRACTED_FROM` edges for a file
- `upsert_from_facts(facts, file_hash=)`: links entities to source File after upsert

### FalkorDB Rules
- `GRAPH.CONSTRAINT CREATE` (not Cypher)
- `result.result_set` → rows as lists, nodes have `.properties`
- `r.key = $val` only in SET, NOT `CREATE ({...})`
- Primitives only — dict→str, list[dict]→list[str]

## ToolCallingService (tool_calling.py)

- **18 tools**: search_reminders, create_reminder, delete_reminder, update_reminder, add_expense, get_expense_report, get_debt_summary, record_debt, pay_debt, get_daily_plan, search_knowledge, store_note, get_person_info, manage_inventory, manage_tasks, manage_projects, merge_projects, get_productivity_stats
- **Chat loop**: LLM picks tools → parallel execution → LLM formats response (max 3 iterations)
- **Streaming**: `chat_stream()` yields NDJSON, tool calls detected from stream
- **Post-processing**: memory + vector + auto-extraction (background `asyncio.create_task`)
- **Auto-extraction**: `_STORABLE_RE` keyword check → NER → translate → extract_facts_specialized → upsert
- **`_AUTO_EXTRACT_SAFE_TYPES`**: only Person, Company, Knowledge, Location from conversation (no bogus Projects/Tasks)
- **`_WRITE_TOOLS`**: skip auto-extraction when write tools already executed
- **Fallback**: `_fallback_reply()` generates simple Arabic from tool results if LLM times out

## RetrievalService (retrieval.py)

- **Ingestion only**: `ingest_text()` → translate → chunk (1500 tokens) → enrich + extract (parallel)
- **Parallel enrichment**: `_enrich_and_store_chunks()` uses `asyncio.gather` — all chunks enrich simultaneously via vLLM continuous batching
- **file_hash tracking**: `ingest_text(file_hash=...)` → stored in each Qdrant point's payload for re-upload cleanup
- **Entity provenance**: `_extract_and_store_facts(text, file_hash=)` → `upsert_from_facts(facts, file_hash=)` → `EXTRACTED_FROM` links
- **Extraction chunking**: hardcoded 3000 tokens (larger context needed for fact extraction)
- **Direct search**: `search_direct()` → translate → vector + graph search
- **NER**: `_run_ner()` → Arabic NER hints for extraction
- No routing, no old pipeline — chat goes through ToolCallingService

## FileService (files.py)

- Image: classify → vision → `_analysis_to_text()` (uses `name_ar:` prefix for Arabic names) → ingest
- PDF: pymupdf4llm; if <200 chars → render pages → vision
- Audio: WhisperX (lazy-loaded, GPU, Arabic)
- Text: decode (utf-8/cp1256/latin-1) → ingest
- **URL**: `process_url()` — GitHub URL parser + generic web fetch → strip HTML → ingest
  - GitHub: repo root → README (main/master fallback), blob → raw file, tree → subpath README
  - Large texts: chunked parallel extraction with entity dedup
- **Re-upload detection**: `process_file()` checks same-filename via `find_file_by_filename()`
  - Same hash → duplicate, skip; same name + different hash → ingest new, delete old chunks, `SUPERSEDES` link
  - Old Qdrant chunks deleted via `delete_by_file_hash(old_hash)`, orphan entities via `cleanup_file_entities(old_hash)`
  - Shared entities (linked to multiple files) survive cleanup
- Storage: `data/files/{hash[:2]}/{hash}.{ext}`

## MemoryService — 3 layers

- **Working**: last N messages (FIFO)
- **Daily summary**: compressed (TTL 7 days)
- **Core**: preferences (permanent Hash)

## BackupService

- `data/backups/{timestamp}/` — graph.json + vector.json + redis.json
- Daily 3 AM, 30-day retention

## NERService

- `CAMeL-Lab/bert-base-arabic-camelbert-msa-ner` (lazy-loaded)
- Extracts Person/Location/Organization (score >= 0.7)
- Prepended as `[NER hints: ...]` to extract prompt
