# Prompts

6 files. Pattern: `build_<name>(args) → list[dict]` (chat messages).

| File | Purpose |
|------|---------|
| tool_system.py | System prompt for tool-calling mode (Arabic, date-aware) |
| extract_specialized.py | **Primary** — 5 domain extractors + general fallback (used by tool-calling auto-extraction) |
| extract.py | General extraction (17 types, 6 examples) — used by ingest pipeline only |
| translate.py | AR↔EN with Saudi dialect examples |
| vision.py | Per-file-type vision instructions (9 types) |
| file_classify.py | Uploaded file type classification |

## Tool System (tool_system.py)

- `build_tool_system_prompt(memory_context, active_project=, user_name=, is_female=)`: Arabic system prompt with current date/time (UTC+3)
- **Gender-aware**: `{user_name}` placeholder throughout; `_FEMALE_REPLACEMENTS` list (11 masculine→feminine Arabic pairs) applied when `is_female=True`
- `tool_calling.py` reads `_current_user_nickname` + `_current_user_gender` context vars and passes them
- Instructions for when to use each of the 25 tools (incl. cross-user: `send_to_user` + `create_reminder` with `target_user`; Home Assistant: `control_device`, `query_device`, `manage_ha_names`)
- Prayer time instruction: LLM maps "بعد صلاة العصر" → `prayer="asr"` param
- Persistent reminder instruction: LLM maps "ولا تخليني أنسى" → `persistent=true`
- Snooze instruction: LLM maps reply "بعد ساعتين"/"بعد المغرب" → `action=snooze` with prayer/time
- Arabic→English entity name translation instruction (e.g. "الستيفنيس" → "Stiffness")
- Expense update/delete instruction: LLM maps "عدل المبلغ" → `add_expense` with `action=update`
- retrieve_file instruction: LLM must call tool every time (not repeat old text); file sent automatically
- HA instruction: LLM maps "شغل النور"→`control_device(action="turn_on")`, "طفي"→`turn_off`; timed HA→`create_reminder` with `ha_entity_id`+`ha_action`
- Anti-lying rules: only say "تم" if tool returned success

## Specialized Extract (extract_specialized.py)

- 5 domain extractors: reminder, finance, inventory, people, productivity (~40% of general prompt size)
- `ROUTE_TO_EXTRACTOR`: maps 19 graph routes → extractor key, unknown routes → general fallback
- `build_specialized_extract(text, route, ner_hints)`: picks extractor, injects date hints + NER
- Each extractor: 2-4 entity types, 1-2 focused examples, catch-all for out-of-domain entities

## Extract (extract.py)

- 17 entity types, 6 examples — used by `ingest_text()` (file/URL ingestion needs all types)
- `build_extract()` injects today/tomorrow for relative dates
- NER hints prepended as `[NER hints: ...]`

## Key Rules

- System + extract prompts MUST include current date/time (UTC+3)
- Tool-calling pipeline: `tool_system.py` prompt + 25 tool definitions (incl. `send_to_user`, `control_device`, `query_device`, `manage_ha_names`)
- Ingest pipeline: general extraction via `extract.py`
