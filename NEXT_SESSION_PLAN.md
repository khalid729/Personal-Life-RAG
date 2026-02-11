# Next Session Plan: Arabic Name Preservation (Auto name_ar)

## Problem
Arabic names go through: Arabic → English translation → stored in graph → model tries to re-arabize → gets it wrong.
Example: رهف → "Rafeh" → "رفيعة" ❌

## Solution: Auto-populate `name_ar` from Arabic NER

### Step 1: Capture Arabic NER names during post-processing

**File:** `app/services/retrieval.py` — `_extract_and_upsert()`

Currently, NER runs on Arabic text and produces hints like `[NER hints: Person: رهف; Location: الخبر]`.
These hints are prepended to the extract prompt but **never stored**.

Change:
- After NER extraction, keep the Arabic names as a dict: `{"Person": ["رهف", "سارة"], "Location": ["الخبر"]}`
- After `upsert_from_facts()`, match English entity names to Arabic NER names using similarity/position
- Call `graph.set_name_ar(english_name, arabic_name)` for each match

### Step 2: Matching algorithm (English ↔ Arabic names)

**File:** `app/services/graph.py` — new method `match_and_set_arabic_names()`

Strategy for matching:
1. **Phonetic similarity**: Transliterate Arabic name to English (simple mapping) and compare
   - رهف → "rhf" vs "Rafeh" → "rfh" — close enough
2. **Position-based**: If NER found 3 persons and extract found 3 persons, match by order
3. **Vector similarity**: Embed both names and compare (most robust but heavier)
4. **LLM-based**: Ask LLM to match names (most accurate, one call per batch)

Recommended: Option 4 (LLM batch matching) — one call with all pairs, most accurate.

### Step 3: Graph context formatting — prefer `name_ar`

**File:** `app/services/graph.py`

In these methods, show `name_ar` as primary name when available:
- `_format_graph_context()` (~line 2691)
- `_format_graph_context_3hop()` (~line 2720)  
- `query_person_context()` fallback summary (~line 1450)

Change: when building context string, if node has `name_ar`, display as:
`"رهف (Rafeh)"` instead of just `"Rafeh"`

### Step 4: Vision/File extraction — preserve Arabic from source

**File:** `app/services/files.py` — `_analysis_to_text()`

For `official_document` and `family_card` types, the vision prompt already extracts Arabic names.
When building the text for ingestion, keep Arabic names as-is (don't translate them).

Change in `_analysis_to_text()`:
- For members list, format as: `"name_ar: رهف, name_en: Rafeh, ..."`
- This way the extract prompt sees both versions

### Step 5: Extract prompt — output `name_ar` field

**File:** `app/prompts/extract.py`

Add to Person entity schema:
- `name_ar` (string, optional): Original Arabic name if available in source text

Update few-shot example to include `name_ar`.

### Step 6: `upsert_person` — accept and store `name_ar`

**File:** `app/services/graph.py` — `upsert_person()`

Already works — `name_ar` passes through via `**props` → `_build_set_clause()`.
Just ensure `name_ar` is NOT in `_INTERNAL_PROPS` (so it shows in context).

## Files to Modify

| File | Change |
|------|--------|
| `app/services/retrieval.py` | Capture NER names, match to entities, store `name_ar` |
| `app/services/graph.py` | `match_and_set_arabic_names()`, context formatting with `name_ar` |
| `app/prompts/extract.py` | Add `name_ar` to Person schema + example |
| `app/services/files.py` | Preserve Arabic names in `_analysis_to_text()` |

## Testing

1. Upload family card → verify `name_ar` auto-populated
2. Ask "اسماء بناتي" → should return رهف, سارة, فرح (not Rafeh, Sarah, Farah)
3. New person mention in chat → verify `name_ar` from NER
4. Query person → context shows Arabic name primarily
