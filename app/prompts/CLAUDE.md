# Prompts

8 files. Pattern: `build_<name>(args) → list[dict]` (chat messages).

| File | Purpose |
|------|---------|
| extract_specialized.py | **Primary** — 5 domain extractors + general fallback (used by chat pipeline) |
| extract.py | General extraction (17 types, 6 examples) — used by ingest pipeline only |
| vision.py | Per-file-type vision instructions (9 types) |
| classify.py | Input categorization (9 categories) |
| translate.py | AR↔EN with Saudi dialect examples |
| conversation.py | Confirmation/action detection (regex-based) |
| agentic.py | Think step (LLM classify fallback) |
| file_classify.py | Uploaded file type classification |

## Specialized Extract (extract_specialized.py)

- 5 domain extractors: reminder, finance, inventory, people, productivity (~40% of general prompt size)
- `ROUTE_TO_EXTRACTOR`: maps 19 graph routes → extractor key, unknown routes → general fallback
- `build_specialized_extract(text, route, ner_hints)`: picks extractor, injects date hints + NER
- Each extractor: 2-4 entity types, 1-2 focused examples, catch-all for out-of-domain entities

## Extract (extract.py)

- 17 entity types, 6 examples — used by `ingest_text()` (file/URL ingestion needs all types)
- `build_extract()` injects today/tomorrow for relative dates
- NER hints prepended as `[NER hints: ...]`

## Conversation (conversation.py)

- `is_delete_intent()` → confirmation required
- All non-delete actions execute directly without asking

## Key Rules

- System + extract prompts MUST include current date/time (UTC+3)
- Chat pipeline: specialized extraction in Stage 2 (parallel with retrieval)
- Ingest pipeline: general extraction via `extract.py`
