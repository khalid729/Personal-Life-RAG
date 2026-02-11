EXTRACT_SYSTEM = """You are a fact extraction engine for a personal knowledge graph.
Extract entities and relationships from the user's text. Be thorough — extract ALL details, numbers, dates, and references mentioned.

Entity types: Person, Company, Project, Idea, Task, Expense, Debt, DebtPayment, Reminder, Knowledge, Topic, Tag, Item, ItemUsage, ItemMove, Sprint

=== Entity details ===

Person: relationship, phone, email, company, notes, date_of_birth (YYYY-MM-DD), id_number

Reminder:
  - reminder_type: "one_time" | "recurring" | "persistent" | "event_based" | "financial"
  - recurrence: "daily" | "weekly" | "monthly" | "yearly" (for recurring type)
  - date: YYYY-MM-DD (the date of the event/appointment itself)
  - time: HH:MM (if mentioned)
  - location: where the event takes place
  - priority: 1-5 (5 = highest)
  - trigger_event: description of triggering event (for event_based)
  - linked_entity: related person/item/project name
  - reference_number: booking/reference/ID number if any
  - IMPORTANT: Always set a concrete date. Never leave date empty.
  - For recurring reminders: set date to the NEXT future occurrence, not the past one.
    Example: event was on 2026-02-11, user wants yearly reminder → date = 2027-02-11 (next year).
    Example: user wants reminder 30 days before next yearly event on 2026-02-11 → date = 2027-01-12.
  - Do NOT use event_based type for simple recurring reminders. Use recurring with recurrence field instead.

Knowledge:
  - Store factual information: locations, reference numbers, details about services, accounts, etc.
  - Include ALL numbers and identifiers (booking numbers, plate numbers, reference IDs, phone numbers).

Expense: amount, currency (default SAR), category, date, vendor
Debt: amount, currency, direction ("i_owe" or "owed_to_me"), reason
DebtPayment: amount, currency — auto-updates existing debt
Item: name, quantity (default 1), location, category, condition, brand
ItemUsage: item name, quantity_used — reduces item quantity
ItemMove: item name, to_location (required), from_location (optional)
Task: priority, estimated_duration (minutes), energy_level (high/medium/low)
Sprint: name, start_date, end_date, goal — link to Project via BELONGS_TO

=== Output format ===

For each entity extract: entity_type, entity_name, properties (key-value pairs), relationships (list of {type, target_type, target_name}).

Date format: YYYY-MM-DD. Respond with ONLY a JSON object:
{
  "entities": [
    {
      "entity_type": "...",
      "entity_name": "...",
      "properties": {...},
      "relationships": [...]
    }
  ]
}

If no entities found: {"entities": []}"""

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
    {
        "input": "Add task: finish the report, high priority, needs deep focus for 2 hours",
        "output": '{"entities": [{"entity_type": "Task", "entity_name": "finish the report", "properties": {"priority": 5, "estimated_duration": 120, "energy_level": "high"}, "relationships": []}]}',
    },
    {
        "input": "Create Sprint 1 for the Smart Home project, 2 weeks starting today",
        "output": '{"entities": [{"entity_type": "Sprint", "entity_name": "Sprint 1", "properties": {"goal": "Smart Home sprint"}, "relationships": [{"type": "BELONGS_TO", "target_type": "Project", "target_name": "Smart Home"}]}]}',
    },
    {
        "input": "Vehicle inspection appointment at Al-Salama Center, Dammam, on 2026-02-11 at 19:30. Plate: 7277TXB. Booking ref: 1025217086.",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "vehicle inspection", "properties": {"reminder_type": "one_time", "date": "2026-02-11", "time": "19:30", "location": "Al-Salama Center, Dammam", "priority": 4, "linked_entity": "7277TXB", "reference_number": "1025217086"}, "relationships": []}, {"entity_type": "Knowledge", "entity_name": "vehicle inspection booking", "properties": {"plate_number": "7277TXB", "booking_number": "1025217086", "location": "Al-Salama Center, Dammam", "date": "2026-02-11", "time": "19:30"}, "relationships": []}]}',
    },
    {
        "input": "Create a yearly reminder for the car inspection. The inspection was on 2026-02-11. Remind me 30 days before.",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "yearly car inspection reminder", "properties": {"reminder_type": "recurring", "recurrence": "yearly", "date": "2027-01-12", "time": "09:00", "priority": 4, "linked_entity": "car inspection"}, "relationships": []}]}',
    },
    {
        "input": "Family card members: Father: EXAMPLE_DAD (born 1980-05-15, ID 1055667788). Mother: EXAMPLE_MOM (born 1985-03-20, ID 1099887766). Son: EXAMPLE_SON (born 2010-11-01, ID 1122334455).",
        "output": '{"entities": [{"entity_type": "Person", "entity_name": "EXAMPLE_DAD", "properties": {"date_of_birth": "1980-05-15", "id_number": "1055667788", "notes": "father"}, "relationships": [{"type": "FAMILY_MEMBER", "target_type": "Person", "target_name": "EXAMPLE_MOM"}, {"type": "FAMILY_MEMBER", "target_type": "Person", "target_name": "EXAMPLE_SON"}]}, {"entity_type": "Person", "entity_name": "EXAMPLE_MOM", "properties": {"date_of_birth": "1985-03-20", "id_number": "1099887766", "notes": "mother"}, "relationships": []}, {"entity_type": "Person", "entity_name": "EXAMPLE_SON", "properties": {"date_of_birth": "2010-11-01", "id_number": "1122334455", "notes": "son"}, "relationships": []}]}',
    },
]

CONTEXT_SYSTEM = """You are a contextual enrichment engine.
Given a chunk of text and the full document it came from, add a brief contextual prefix (1-2 sentences) that situates this chunk within the broader document.

The context should help a search engine understand what this chunk is about even when read in isolation.

Respond with ONLY the contextualized chunk in this format:
"[Context: <brief context>] <original chunk text>"
"""


def build_extract(text: str, ner_hints: str = "") -> list[dict]:
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

    user_content = text
    if ner_hints:
        user_content = f"[NER hints: {ner_hints}]\n\n{text}"
    messages.append({"role": "user", "content": user_content})
    return messages


def build_context_enrichment(chunk: str, full_document: str) -> list[dict]:
    return [
        {"role": "system", "content": CONTEXT_SYSTEM},
        {
            "role": "user",
            "content": f"Full document:\n{full_document[:2000]}\n\n---\nChunk to contextualize:\n{chunk}",
        },
    ]
