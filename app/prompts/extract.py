EXTRACT_SYSTEM = """You are a fact extraction engine for a personal knowledge graph.
Extract entities and relationships from the user's text.

Entity types: Person, Company, Project, Idea, Task, Expense, Debt, Reminder, Knowledge, Topic, Tag

For each entity, extract:
- entity_type: one of the types above
- entity_name: the name/title
- properties: key-value pairs (e.g. amount, date, status, category, description)
- relationships: list of {type, target_type, target_name} (e.g. WORKS_AT, BELONGS_TO, OWES, RELATED_TO)

Date format: YYYY-MM-DD. Currency amounts should include the value and currency (default SAR).

Respond with ONLY a JSON object:
{
  "entities": [
    {
      "entity_type": "Expense",
      "entity_name": "lunch",
      "properties": {"amount": 45, "currency": "SAR", "category": "food", "date": "2025-01-15"},
      "relationships": [{"type": "PAID_AT", "target_type": "Company", "target_name": "McDonalds"}]
    }
  ]
}

If no entities can be extracted, return: {"entities": []}"""

EXTRACT_EXAMPLES = [
    {
        "input": "Ahmad owes me 500 SAR for the dinner last week",
        "output": '{"entities": [{"entity_type": "Debt", "entity_name": "dinner debt", "properties": {"amount": 500, "currency": "SAR", "direction": "owed_to_me", "reason": "dinner"}, "relationships": [{"type": "OWES", "target_type": "Person", "target_name": "Ahmad"}]}, {"entity_type": "Person", "entity_name": "Ahmad", "properties": {}, "relationships": []}]}',
    },
    {
        "input": "I spent 200 riyals on groceries at Tamimi today",
        "output": '{"entities": [{"entity_type": "Expense", "entity_name": "groceries", "properties": {"amount": 200, "currency": "SAR", "category": "groceries"}, "relationships": [{"type": "PAID_AT", "target_type": "Company", "target_name": "Tamimi"}]}, {"entity_type": "Company", "entity_name": "Tamimi", "properties": {"industry": "retail"}, "relationships": []}]}',
    },
]

CONTEXT_SYSTEM = """You are a contextual enrichment engine.
Given a chunk of text and the full document it came from, add a brief contextual prefix (1-2 sentences) that situates this chunk within the broader document.

The context should help a search engine understand what this chunk is about even when read in isolation.

Respond with ONLY the contextualized chunk in this format:
"[Context: <brief context>] <original chunk text>"
"""


def build_extract(text: str) -> list[dict]:
    messages = [{"role": "system", "content": EXTRACT_SYSTEM}]
    for ex in EXTRACT_EXAMPLES:
        messages.append({"role": "user", "content": ex["input"]})
        messages.append({"role": "assistant", "content": ex["output"]})
    messages.append({"role": "user", "content": text})
    return messages


def build_context_enrichment(chunk: str, full_document: str) -> list[dict]:
    return [
        {"role": "system", "content": CONTEXT_SYSTEM},
        {
            "role": "user",
            "content": f"Full document:\n{full_document[:2000]}\n\n---\nChunk to contextualize:\n{chunk}",
        },
    ]
