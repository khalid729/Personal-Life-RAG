EXTRACT_SYSTEM = """You are a fact extraction engine for a personal knowledge graph.
Extract entities and relationships from the user's text.

Entity types: Person, Company, Project, Idea, Task, Expense, Debt, DebtPayment, Reminder, Knowledge, Topic, Tag, Item, ItemUsage, ItemMove

Special entity types:
- DebtPayment (pseudo-entity): Use when someone pays back or settles a debt. Keywords: "سدد", "رجع", "دفع له", "paid back", "settled", "returned the money". Extract the person and amount. This will automatically update the existing debt record.
- Item: A physical possession or inventory item. Keywords: "عندي", "شريت", "في السطح", "في الدرج", "bought", "i have", "stored in". Extract name, quantity (default 1), location, category, condition, brand.
- ItemUsage (pseudo-entity): When items are consumed/used/given away/lost. Keywords: "استخدمت", "ضاع", "عطيت", "خلصت", "used", "gave away", "lost", "consumed", "broke". Extract item name and quantity_used. This reduces the item's quantity in inventory.
- ItemMove (pseudo-entity): When items are moved between locations. Keywords: "نقلت", "حركت", "حطيته في", "moved", "relocated", "transferred". Extract item name, to_location (required), from_location (optional). This updates the item's storage location.
- Reminder subtypes via properties:
  - reminder_type: "one_time" (default), "recurring" (repeating schedule), "persistent" (don't forget until done), "event_based" (triggered by an event), "financial" (payment/bill related)
  - recurrence: "daily", "weekly", "monthly", "yearly" (for recurring type)
  - priority: 1-5 (5 = highest, use for persistent/urgent reminders)
  - trigger_event: description of triggering event (for event_based type)
  - linked_entity: name of related person/project (if applicable)

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
        "input": "I owe Fahd 800 riyals for the car repair",
        "output": '{"entities": [{"entity_type": "Debt", "entity_name": "car repair debt", "properties": {"amount": 800, "currency": "SAR", "direction": "i_owe", "reason": "car repair"}, "relationships": [{"type": "OWES", "target_type": "Person", "target_name": "Fahd"}]}, {"entity_type": "Person", "entity_name": "Fahd", "properties": {}, "relationships": []}]}',
    },
    {
        "input": "I spent 200 riyals on groceries at Tamimi today",
        "output": '{"entities": [{"entity_type": "Expense", "entity_name": "groceries", "properties": {"amount": 200, "currency": "SAR", "category": "groceries"}, "relationships": [{"type": "PAID_AT", "target_type": "Company", "target_name": "Tamimi"}]}, {"entity_type": "Company", "entity_name": "Tamimi", "properties": {"industry": "retail"}, "relationships": []}]}',
    },
    {
        "input": "Ahmad paid back 200 SAR from the dinner debt",
        "output": '{"entities": [{"entity_type": "DebtPayment", "entity_name": "dinner debt payment", "properties": {"amount": 200, "currency": "SAR"}, "relationships": [{"type": "PAID_BY", "target_type": "Person", "target_name": "Ahmad"}]}]}',
    },
    {
        "input": "Remind me to pay rent on the 1st of every month",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "pay rent", "properties": {"reminder_type": "recurring", "recurrence": "monthly", "priority": 4}, "relationships": []}]}',
    },
    {
        "input": "Don't let me forget to renew the car registration",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "renew car registration", "properties": {"reminder_type": "persistent", "priority": 5}, "relationships": []}]}',
    },
    {
        "input": "I have 5 USB-C cables stored in the roof storage on the second shelf",
        "output": '{"entities": [{"entity_type": "Item", "entity_name": "USB-C cable", "properties": {"quantity": 5, "location": "السطح > الرف الثاني", "category": "cables"}, "relationships": []}]}',
    },
    {
        "input": "I used 2 USB-C cables from the roof storage",
        "output": '{"entities": [{"entity_type": "ItemUsage", "entity_name": "USB-C cable", "properties": {"quantity_used": 2}, "relationships": []}]}',
    },
    {
        "input": "I moved the printer from the roof to the office",
        "output": '{"entities": [{"entity_type": "ItemMove", "entity_name": "printer", "properties": {"to_location": "المكتب", "from_location": "السطح"}, "relationships": []}]}',
    },
]

CONTEXT_SYSTEM = """You are a contextual enrichment engine.
Given a chunk of text and the full document it came from, add a brief contextual prefix (1-2 sentences) that situates this chunk within the broader document.

The context should help a search engine understand what this chunk is about even when read in isolation.

Respond with ONLY the contextualized chunk in this format:
"[Context: <brief context>] <original chunk text>"
"""


def build_extract(text: str) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    from app.config import get_settings as _gs
    riyadh_tz = timezone(timedelta(hours=_gs().timezone_offset_hours))
    now = datetime.now(riyadh_tz)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    date_hint = f"\n\nToday's date: {today}. Tomorrow: {tomorrow}. Use these to resolve relative dates like 'بكرة', 'tomorrow', 'next week', etc."

    messages = [{"role": "system", "content": EXTRACT_SYSTEM + date_hint}]
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
