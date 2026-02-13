# Services

8 async services with `start()`/`stop()` lifecycle, injected via `app.state`.

## Service Map

| Service | File | Backend |
|---------|------|---------|
| LLMService | llm.py | vLLM :8000 (httpx) |
| GraphService | graph.py (110KB) | FalkorDB :6379 |
| VectorService | vector.py | Qdrant :6333 + BGE-M3 GPU |
| MemoryService | memory.py | Redis :6380 (3 layers) |
| RetrievalService | retrieval.py (49KB) | Orchestrates all above |
| FileService | files.py | Image/PDF/audio processing |
| BackupService | backup.py | Timestamped snapshots |
| NERService | ner.py | CAMeL-Lab Arabic BERT NER |

## Dependencies

```
RetrievalService(llm, graph, vector, memory, ner)
FileService(llm, retrieval)
BackupService(graph, vector, memory)
GraphService.set_vector_service(vector)  # entity resolution
```

## GraphService (graph.py)

- 15+ entity types: Person, Company, Project, Task, Expense, Debt, Reminder, Knowledge, Item, Sprint, etc.
- `resolve_entity_name(name, label)`: vector similarity → canonical name
- `upsert_person()`: auto Hijri→Gregorian for year < 1900
- `_display_name(props)`: `"رهف (Rahaf)"` if `name_ar` exists
- `_build_set_clause()`: skips empty strings
- `_format_graph_context()` / `_3hop()`: multi-hop results for LLM, uses `_display_name()`
- `query_projects_overview()`: case-insensitive status filter via `toLower()`

### FalkorDB Rules
- `GRAPH.CONSTRAINT CREATE` (not Cypher)
- `result.result_set` → rows as lists, nodes have `.properties`
- `r.key = $val` only in SET, NOT `CREATE ({...})`
- Primitives only — dict→str, list[dict]→list[str]

## RetrievalService (retrieval.py)

- **Routing**: 20 keyword patterns → fast-path, fallback LLM classify
- **Pipeline**: Think → Act → Reflect (score chunks, filter < 0.3) → retry if insufficient
- **Post-processing**: BackgroundTasks extracts from query + combined exchange (both with NER hints, dedup by entity type)
- **Confirmation**: delete/cancel only; clarification skipped if NER found entities

## FileService (files.py)

- Image: classify → vision → `_analysis_to_text()` (uses `name_ar:` prefix for Arabic names) → ingest
- PDF: pymupdf4llm; if <200 chars → render pages → vision
- Audio: WhisperX (lazy-loaded, GPU, Arabic)
- Text: decode (utf-8/cp1256/latin-1) → ingest
- **URL**: `process_url()` — GitHub URL parser + generic web fetch → strip HTML → ingest
  - GitHub: repo root → README (main/master fallback), blob → raw file, tree → subpath README
  - Large texts: chunked parallel extraction with entity dedup
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
- Extracts Person/Location/Organization (score ≥ 0.7)
- Prepended as `[NER hints: ...]` to extract prompt
