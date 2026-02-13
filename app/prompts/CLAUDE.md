# Prompts

7 files. Pattern: `build_<name>(args) → list[dict]` (chat messages).

| File | Purpose |
|------|---------|
| extract.py | Entity extraction (16 types, 6 few-shot examples) |
| vision.py | Per-file-type vision instructions (9 types) |
| classify.py | Input categorization (9 categories) |
| translate.py | AR↔EN with Saudi dialect examples |
| conversation.py | Confirmation/action detection (regex-based) |
| agentic.py | Think→Act→Reflect pipeline |
| file_classify.py | Uploaded file type classification |

## Extract (extract.py)

- 16 entity types, 6 examples (debt, expense, reminder, item, NER→name_ar, knowledge+ref)
- Person: `name_ar` from NER hints — copy exactly, don't transliterate
- Reminder: date REQUIRED, recurring = NEXT future occurrence
- `build_extract()` injects today/tomorrow for relative dates
- NER hints prepended as `[NER hints: ...]`

## Conversation (conversation.py)

- `is_delete_intent()` → confirmation required
- `is_action_intent()` → side-effect detection
- All non-delete actions execute directly without asking

## Key Rules

- System + extract prompts MUST include current date/time (UTC+3)
- Clarification skipped if NER found named entities
- Post-processing: query extraction + combined extraction (dedup by entity type)
