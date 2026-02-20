EXTRACT_SYSTEM = """You are a fact extraction engine for a personal knowledge graph.
Extract entities and relationships from the user's text. Be thorough — extract ALL details, numbers, dates, and references.

Entity types: Person, Company, Project, Idea, Task, Expense, Debt, DebtPayment, Reminder, ReminderAction, Knowledge, Topic, Tag, Item, ItemUsage, ItemMove, Sprint

=== Entity details ===

Person: relationship, phone, email, company, notes, date_of_birth (YYYY-MM-DD), id_number, name_ar (Arabic name from NER hints or source text — copy exactly, do not transliterate)

Reminder:
  - reminder_type: "one_time" | "recurring" | "persistent" | "event_based" | "financial"
  - recurrence: "daily" | "weekly" | "monthly" | "yearly" (for recurring)
  - due_date: YYYY-MM-DD (REQUIRED — always set a concrete date, resolve 'بكرة'/'tomorrow' using today's date below)
  - time: HH:MM (if mentioned)
  - location, priority (1-5), trigger_event, linked_entity, reference_number
  - For recurring: due_date = NEXT future occurrence, not past.
  - IMPORTANT: Use consistent lowercase titles. If a similar reminder likely exists, reuse its exact title.

Knowledge: store factual info — locations, reference numbers, IDs, accounts, etc.

Expense: amount, currency (default SAR), category, date, vendor
Debt: amount, currency, direction ("i_owe" or "owed_to_me"), reason
DebtPayment: amount, currency — auto-updates existing debt
ReminderAction: action ("done" | "snooze" | "cancel"), reminder_title — marks reminder completed/snoozed/cancelled. Use when user finished, received, picked up, or completed the thing the reminder was about.
Item: name, quantity (default 1), location, category, condition, brand
ItemUsage: item name, quantity_used — reduces item quantity
ItemMove: item name, to_location (required), from_location (optional)
Task: priority, estimated_duration (minutes), energy_level (high/medium/low)
Sprint: name, start_date, end_date, goal — link to Project via BELONGS_TO

=== Output format ===

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}

If no entities found: {"entities": []}"""

EXTRACT_EXAMPLES = [
    {
        "input": "Ahmad owes me 500 SAR for the dinner last week",
        "output": '{"entities": [{"entity_type": "Debt", "entity_name": "dinner debt", "properties": {"amount": 500, "currency": "SAR", "direction": "owed_to_me", "reason": "dinner"}, "relationships": [{"type": "OWES", "target_type": "Person", "target_name": "Ahmad"}]}, {"entity_type": "Person", "entity_name": "Ahmad", "properties": {}, "relationships": []}]}',
    },
    {
        "input": "I spent 200 riyals on groceries at Tamimi today",
        "output": '{"entities": [{"entity_type": "Expense", "entity_name": "groceries", "properties": {"amount": 200, "currency": "SAR", "category": "groceries"}, "relationships": [{"type": "PAID_AT", "target_type": "Company", "target_name": "Tamimi"}]}]}',
    },
    {
        "input": "Remind me to pay rent on the 1st of every month",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "pay rent", "properties": {"reminder_type": "recurring", "recurrence": "monthly", "due_date": "2026-03-01", "priority": 4}, "relationships": []}]}',
    },
    {
        "input": "I have 5 USB-C cables stored in the roof storage on the second shelf",
        "output": '{"entities": [{"entity_type": "Item", "entity_name": "USB-C cable", "properties": {"quantity": 5, "location": "السطح > الرف الثاني", "category": "cables"}, "relationships": []}]}',
    },
    {
        "input": "[NER hints: Detected entities: Person: رهف]\n\nMy daughter Rafeh got an A in math",
        "output": '{"entities": [{"entity_type": "Person", "entity_name": "Rafeh", "properties": {"name_ar": "رهف", "notes": "daughter, got A in math"}, "relationships": []}]}',
    },
    {
        "input": "Vehicle inspection at Al-Salama Center, Dammam, on 2026-02-11 at 19:30. Plate: 7277TXB. Booking ref: 1025217086.",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "vehicle inspection", "properties": {"reminder_type": "one_time", "due_date": "2026-02-11", "time": "19:30", "location": "Al-Salama Center, Dammam", "priority": 4, "reference_number": "1025217086"}, "relationships": []}, {"entity_type": "Knowledge", "entity_name": "vehicle inspection booking", "properties": {"plate_number": "7277TXB", "booking_number": "1025217086", "location": "Al-Salama Center, Dammam"}, "relationships": []}]}',
    },
]

CONTEXT_SYSTEM = """You are a contextual enrichment engine.
Given a chunk of text and the full document it came from, add a brief contextual prefix (1-2 sentences) that situates this chunk within the broader document.

The context should help a search engine understand what this chunk is about even when read in isolation.

Respond with ONLY the contextualized chunk in this format:
"[Context: <brief context>] <original chunk text>"
"""


def build_extract(text: str, ner_hints: str = "", project_name: str | None = None) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    from app.config import get_settings as _gs
    riyadh_tz = timezone(timedelta(hours=_gs().timezone_offset_hours))
    now = datetime.now(riyadh_tz)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    date_hint = f"\n\nToday's date: {today}. Tomorrow: {tomorrow}. Use these to resolve relative dates like 'بكرة', 'tomorrow', 'next week', etc."

    system_content = EXTRACT_SYSTEM + date_hint

    if project_name:
        system_content += f"""

=== Active Project Context ===
The user is currently focused on the project: "{project_name}".
- Do NOT create new Project entities. The project already exists.
- For entities related to this project (Task, Knowledge, Idea, Sprint), add a relationship:
  {{"type": "BELONGS_TO", "target_type": "Project", "target_name": "{project_name}"}}
- Other entity types (Person, Company, Expense, etc.) are global — extract normally."""

    messages = [{"role": "system", "content": system_content}]
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
