"""Specialized extraction prompts — domain-focused, ~200 tokens each vs ~650 for general."""

from datetime import datetime, timedelta, timezone

from app.config import get_settings as _gs

# --- Route → Extractor mapping ---

ROUTE_TO_EXTRACTOR = {
    "graph_reminder": "reminder",
    "graph_reminder_action": "reminder",
    "graph_financial": "finance",
    "graph_financial_report": "finance",
    "graph_debt_summary": "finance",
    "graph_debt_payment": "finance",
    "graph_inventory": "inventory",
    "graph_inventory_unused": "inventory",
    "graph_inventory_report": "inventory",
    "graph_inventory_duplicates": "inventory",
    "graph_person": "people",
    "graph_knowledge": "people",
    "graph_project": "productivity",
    "graph_task": "productivity",
    "graph_sprint": "productivity",
    "graph_daily_plan": "productivity",
    "graph_focus_stats": "productivity",
    "graph_timeblock": "productivity",
    "graph_productivity_report": "productivity",
    "multi_intent": "general",
}

# --- Extractor system prompts ---

REMINDER_SYSTEM = """You are a fact extraction engine for reminders.

Entity types: Reminder, ReminderAction

Reminder: entity_name = short title (lowercase)
  Properties: reminder_type ("one_time"|"recurring"|"persistent"|"event_based"|"financial"), recurrence ("daily"|"weekly"|"monthly"|"yearly"), due_date (YYYY-MM-DD, REQUIRED), time (HH:MM), location, priority (1-5), trigger_event, linked_entity, reference_number
  For recurring: due_date = NEXT future occurrence.

ReminderAction: entity_name = action description
  Properties: action ("done"|"snooze"|"cancel"|"delete"), reminder_title (exact title of existing reminder)
  Use when user finished, received, picked up, completed, deleted, or removed something.

If you see entities outside your specialty, include them with entity_type and entity_name only.

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}
If no entities: {"entities": []}"""

REMINDER_EXAMPLES = [
    {
        "input": "Remind me to pay rent tomorrow",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "pay rent", "properties": {"reminder_type": "one_time", "due_date": "{tomorrow}", "priority": 4}, "relationships": []}]}',
    },
    {
        "input": "I received the shipments",
        "output": '{"entities": [{"entity_type": "ReminderAction", "entity_name": "shipments received", "properties": {"action": "done", "reminder_title": "shipments"}, "relationships": []}]}',
    },
    {
        "input": "Delete the family iftar reminder",
        "output": '{"entities": [{"entity_type": "ReminderAction", "entity_name": "delete family iftar", "properties": {"action": "delete", "reminder_title": "family iftar at home"}, "relationships": []}]}',
    },
]

FINANCE_SYSTEM = """You are a fact extraction engine for financial data.

Entity types: Expense, Debt, DebtPayment

Expense: entity_name = expense description
  Properties: amount (number), currency (default SAR), category, date (YYYY-MM-DD), vendor
  Relationships: PAID_AT → Company

Debt: entity_name = debt reason
  Properties: amount, currency, direction ("i_owe"|"owed_to_me"), reason
  Relationships: OWES → Person

DebtPayment: entity_name = payment description
  Properties: amount, currency
  Relationships: PAID_BY/PAID_TO → Person

If you see entities outside your specialty, include them with entity_type and entity_name only.

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}
If no entities: {"entities": []}"""

FINANCE_EXAMPLES = [
    {
        "input": "I spent 200 riyals on groceries at Tamimi today",
        "output": '{"entities": [{"entity_type": "Expense", "entity_name": "groceries", "properties": {"amount": 200, "currency": "SAR", "category": "groceries"}, "relationships": [{"type": "PAID_AT", "target_type": "Company", "target_name": "Tamimi"}]}]}',
    },
    {
        "input": "Ahmad owes me 500 SAR for the dinner",
        "output": '{"entities": [{"entity_type": "Debt", "entity_name": "dinner debt", "properties": {"amount": 500, "currency": "SAR", "direction": "owed_to_me", "reason": "dinner"}, "relationships": [{"type": "OWES", "target_type": "Person", "target_name": "Ahmad"}]}, {"entity_type": "Person", "entity_name": "Ahmad", "properties": {}, "relationships": []}]}',
    },
]

INVENTORY_SYSTEM = """You are a fact extraction engine for inventory/items.

Entity types: Item, ItemUsage, ItemMove

Item: entity_name = item name (singular, lowercase)
  Properties: quantity (default 1), location, category, condition, brand

ItemUsage: entity_name = item name
  Properties: quantity_used (default 1) — reduces item quantity

ItemMove: entity_name = item name
  Properties: to_location (required), from_location (optional)

If you see entities outside your specialty, include them with entity_type and entity_name only.

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}
If no entities: {"entities": []}"""

INVENTORY_EXAMPLES = [
    {
        "input": "I have 5 USB-C cables stored in the roof storage on the second shelf",
        "output": '{"entities": [{"entity_type": "Item", "entity_name": "USB-C cable", "properties": {"quantity": 5, "location": "roof storage > second shelf", "category": "cables"}, "relationships": []}]}',
    },
    {
        "input": "I moved the printer to the office",
        "output": '{"entities": [{"entity_type": "ItemMove", "entity_name": "printer", "properties": {"to_location": "office"}, "relationships": []}]}',
    },
]

PEOPLE_SYSTEM = """You are a fact extraction engine for people and knowledge.

Entity types: Person, Company, Knowledge, Topic, Tag

Person: entity_name = person name
  Properties: relationship, phone, email, company, notes, date_of_birth (YYYY-MM-DD), id_number, name_ar (Arabic name from NER hints — copy exactly, do not transliterate)

Knowledge: entity_name = knowledge title
  Properties: any factual info — locations, reference numbers, IDs, accounts, etc.

Company: entity_name = company name
  Properties: industry, notes

Topic/Tag: entity_name = topic/tag name

If you see entities outside your specialty, include them with entity_type and entity_name only.

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}
If no entities: {"entities": []}"""

PEOPLE_EXAMPLES = [
    {
        "input": "[NER hints: Detected entities: Person: رهف]\n\nMy daughter Rafeh got an A in math",
        "output": '{"entities": [{"entity_type": "Person", "entity_name": "Rafeh", "properties": {"name_ar": "رهف", "notes": "daughter, got A in math"}, "relationships": []}]}',
    },
]

PRODUCTIVITY_SYSTEM = """You are a fact extraction engine for tasks and projects.

Entity types: Task, Project, Sprint, Idea, Section, List

Task: entity_name = task title
  Properties: priority (1-5), estimated_duration (minutes), energy_level (high/medium/low), status (todo/in_progress/done/cancelled)
  Relationships: BELONGS_TO → Project

Project: entity_name = project name
  Properties: description, status (idea/planning/active/paused/done/cancelled), priority

Sprint: entity_name = sprint name
  Properties: start_date, end_date, goal, status
  Relationships: BELONGS_TO → Project

Idea: entity_name = idea title
  Properties: description, category

Section: section_type ("topic"|"phase"), order (for phases), description
  Relationships: belongs to Project via HAS_SECTION
List: list_type ("shopping"|"ideas"|"checklist"|"reference")
  Relationships: optional BELONGS_TO → Project

If you see entities outside your specialty, include them with entity_type and entity_name only.

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}
If no entities: {"entities": []}"""

PRODUCTIVITY_EXAMPLES = [
    {
        "input": "Add a task to fix the login bug, high priority, about 2 hours",
        "output": '{"entities": [{"entity_type": "Task", "entity_name": "fix login bug", "properties": {"priority": 5, "estimated_duration": 120, "energy_level": "high", "status": "todo"}, "relationships": []}]}',
    },
]

GENERAL_SYSTEM = """You are a fact extraction engine for a personal knowledge graph.
Extract entities and relationships from the user's text. Be thorough.

Entity types: Person, Company, Project, Idea, Task, Expense, Debt, DebtPayment, Reminder, ReminderAction, Knowledge, Topic, Tag, Item, ItemUsage, ItemMove, Sprint, Section, List

Person: relationship, phone, email, company, notes, date_of_birth, id_number, name_ar (Arabic name from NER hints — copy exactly)
Reminder: reminder_type, recurrence, due_date (YYYY-MM-DD, REQUIRED), time, location, priority, reference_number
ReminderAction: action ("done"|"snooze"|"cancel"|"delete"), reminder_title
Expense: amount, currency (SAR), category, date, vendor
Debt: amount, currency, direction ("i_owe"|"owed_to_me"), reason
DebtPayment: amount, currency
Item: quantity (default 1), location, category, condition, brand
ItemUsage: quantity_used — reduces item quantity
ItemMove: to_location (required), from_location (optional)
Task: priority, estimated_duration (minutes), energy_level, status (todo/in_progress/done/cancelled)
Knowledge: factual info — locations, reference numbers, IDs, accounts
Sprint: start_date, end_date, goal
Section: section_type ("topic"|"phase"), order (for phases), description
  Relationships: belongs to Project via HAS_SECTION
List: list_type ("shopping"|"ideas"|"checklist"|"reference")
  Relationships: optional BELONGS_TO → Project

JSON only:
{"entities": [{"entity_type": "...", "entity_name": "...", "properties": {...}, "relationships": [{"type": "...", "target_type": "...", "target_name": "..."}]}]}
If no entities: {"entities": []}"""

GENERAL_EXAMPLES = [
    {
        "input": "I spent 200 riyals on groceries at Tamimi today",
        "output": '{"entities": [{"entity_type": "Expense", "entity_name": "groceries", "properties": {"amount": 200, "currency": "SAR", "category": "groceries"}, "relationships": [{"type": "PAID_AT", "target_type": "Company", "target_name": "Tamimi"}]}]}',
    },
    {
        "input": "Remind me to pay rent on the 1st of every month",
        "output": '{"entities": [{"entity_type": "Reminder", "entity_name": "pay rent", "properties": {"reminder_type": "recurring", "recurrence": "monthly", "due_date": "2026-03-01", "priority": 4}, "relationships": []}]}',
    },
    {
        "input": "Ahmad owes me 500 SAR for dinner",
        "output": '{"entities": [{"entity_type": "Debt", "entity_name": "dinner debt", "properties": {"amount": 500, "currency": "SAR", "direction": "owed_to_me", "reason": "dinner"}, "relationships": [{"type": "OWES", "target_type": "Person", "target_name": "Ahmad"}]}, {"entity_type": "Person", "entity_name": "Ahmad", "properties": {}, "relationships": []}]}',
    },
]

# --- Registry ---

_EXTRACTORS = {
    "reminder": (REMINDER_SYSTEM, REMINDER_EXAMPLES),
    "finance": (FINANCE_SYSTEM, FINANCE_EXAMPLES),
    "inventory": (INVENTORY_SYSTEM, INVENTORY_EXAMPLES),
    "people": (PEOPLE_SYSTEM, PEOPLE_EXAMPLES),
    "productivity": (PRODUCTIVITY_SYSTEM, PRODUCTIVITY_EXAMPLES),
    "general": (GENERAL_SYSTEM, GENERAL_EXAMPLES),
}


def build_specialized_extract(text: str, route: str, ner_hints: str = "", conversation_context: str = "") -> list[dict]:
    """Build chat messages for a specialized extractor based on route.

    Picks the correct domain extractor, injects date hints, prepends NER hints.
    Falls back to 'general' extractor for unknown routes.
    """
    extractor_key = ROUTE_TO_EXTRACTOR.get(route, "general")
    system_prompt, examples = _EXTRACTORS[extractor_key]

    # Inject today/tomorrow date hint
    riyadh_tz = timezone(timedelta(hours=_gs().timezone_offset_hours))
    now = datetime.now(riyadh_tz)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    date_hint = f"\n\nToday's date: {today}. Tomorrow: {tomorrow}. Use these to resolve relative dates like 'tomorrow', 'next week', etc."

    messages = [{"role": "system", "content": system_prompt + date_hint}]

    # Add few-shot examples (resolve {tomorrow} placeholder in reminder examples)
    for ex in examples:
        output = ex["output"].replace("{tomorrow}", tomorrow)
        messages.append({"role": "user", "content": ex["input"]})
        messages.append({"role": "assistant", "content": output})

    # Build user content with optional NER hints and conversation context
    user_content = text
    if ner_hints:
        user_content = f"[NER hints: {ner_hints}]\n\n{text}"
    if conversation_context:
        user_content = f"[Recent conversation context: {conversation_context}]\n\n{user_content}"
    messages.append({"role": "user", "content": user_content})

    return messages
