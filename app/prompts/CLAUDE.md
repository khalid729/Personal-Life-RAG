# Prompts

7 prompt files, all export system prompts + builder functions. Pattern: `build_<name>(args) → list[dict]` (chat messages).

## Files

| File | Exports | Purpose |
|------|---------|---------|
| extract.py | `EXTRACT_SYSTEM`, `EXTRACT_EXAMPLES`, `build_extract(text, ner_hints)` | Entity/relationship extraction (16 types) |
| vision.py | `VISION_PROMPTS` dict (11 types), `build_vision_analysis()` | Per-file-type vision instructions |
| classify.py | `CLASSIFY_SYSTEM`, `build_classify()` | Input categorization (9 categories) |
| translate.py | `AR_TO_EN_SYSTEM`, `AR_TO_EN_EXAMPLES`, `EN_TO_AR_SYSTEM` | AR↔EN with Saudi dialect examples |
| conversation.py | `is_delete_intent()`, `is_confirmation()`, `is_action_intent()`, confirmation builders | Conversation flow control |
| agentic.py | `THINK_SYSTEM`, `build_think()`, `build_reflect()` | Think→Act→Reflect pipeline |
| file_classify.py | `FILE_CLASSIFY_SYSTEM`, `build_file_classify()` | Classify uploaded file type |

## Extract Prompt (extract.py) — Most Complex

Entity types: Person, Company, Project, Idea, Task, Expense, Debt, DebtPayment, Reminder, Knowledge, Topic, Tag, Item, ItemUsage, ItemMove, Sprint

Key rules:
- Person: has `date_of_birth` (YYYY-MM-DD), `id_number`
- Reminder: MUST have concrete `date`, never empty
- Recurring: date = NEXT future occurrence (e.g. yearly 2026-02-11 → 2027-02-11)
- "30 days before" → next_year - 30 days
- Do NOT use `event_based` for simple recurring — use `recurring` + `recurrence`
- Knowledge: include ALL reference numbers, booking numbers, plate numbers, IDs
- `build_extract()` auto-injects today's date + tomorrow for relative date resolution
- NER hints prepended as `[NER hints: ...]` to user content

## Vision Prompts (vision.py)

11 file types: invoice, official_document, personal_photo, info_image, note, project_file, price_list, business_card, inventory_item, pdf_document, audio_recording

`official_document` includes: text_content, dates (with hijri), reference_numbers, parties, members (name/DOB/ID/role)

## Conversation Flow (conversation.py)

- `CONFIRM_YES` / `CONFIRM_NO`: regex patterns for yes/no in Arabic + English
- `is_delete_intent(text)`: matches حذف/الغي/delete/remove/cancel
- `is_action_intent(text)`: detects expense/reminder/task creation
- Confirmation ONLY for delete/cancel — everything else runs directly
- `SIDE_EFFECT_ROUTES`: routes that trigger post-processing

## Important Rules

- System prompt + extract prompt MUST include current date/time (UTC+3)
- Clarification is skipped if extraction found named entities
- Post-processing extracts from query alone AND combined exchange (dedup by entity type)
