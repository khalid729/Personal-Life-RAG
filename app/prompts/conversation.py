"""Phase 4: Conversation prompts — confirmation, clarification, action detection."""

import re

# --- Confirmation pattern matching ---

CONFIRM_YES = re.compile(
    r"^(نعم|أي|ايوا|اي|تمام|اوكي|ماشي|صح|أكيد|اكيد|يب|طيب|"
    r"yes|ok|okay|sure|yep|yeah|yea|confirm|go ahead)$",
    re.IGNORECASE,
)

CONFIRM_NO = re.compile(
    r"^(لا|لأ|الغي|الغ|كنسل|خلاص لا|ما ابي|لا شكراً|"
    r"no|nah|nope|cancel|nevermind|never mind|stop)$",
    re.IGNORECASE,
)

NUMBER_SELECTION = re.compile(r"^\d+$")


def is_confirmation(text: str) -> str | None:
    """Check if text is a yes/no confirmation. Returns 'yes', 'no', or None."""
    text = text.strip()
    if CONFIRM_YES.match(text):
        return "yes"
    if CONFIRM_NO.match(text):
        return "no"
    return None


# --- Action vs Query detection (zero-latency heuristic) ---

ACTION_PATTERNS = re.compile(
    r"(صرفت|دفعت|سددت|سدد|رجع|سجل|ذكرني|أضف|ضيف|حط|اشتريت|عندي |شريت|"
    r"استخدمت|ضاع|خلص|عطيت|رميت|انكسر|"
    r"نقلت|حركت|حطيته في|حطيتها في|moved|relocated|transferred|"
    r"spent|paid|record|add|bought|create|register|remind me|set reminder|i have|stored|"
    r"used|gave away|lost|broke)",
    re.IGNORECASE,
)

QUERY_PATTERNS = re.compile(
    r"(كم|وش|مين|ملخص|تقرير|عرض|ابي اعرف|اعرض|"
    r"how much|who|what|show|list|summary|report|display|tell me)",
    re.IGNORECASE,
)

# Patterns that indicate a DELETE/REMOVE/CANCEL intent (confirmation required)
DELETE_PATTERNS = re.compile(
    r"(احذف|حذف|امحي|امسح|شيل|ازل|الغي|الغاء|كنسل|فك|"
    r"delete|remove|cancel|erase|clear|drop|wipe)",
    re.IGNORECASE,
)

# Routes that always create side-effects
SIDE_EFFECT_ROUTES = {
    "graph_financial",
    "graph_debt_payment",
    "graph_reminder",
    "graph_reminder_action",
    "graph_inventory",
}

# Deterministic route→intent mapping (no heuristic needed)
_ALWAYS_ACTION = {"graph_debt_payment", "graph_reminder_action"}
_ALWAYS_QUERY = {"graph_debt_summary", "graph_financial_report"}


def is_action_intent(text: str, route: str) -> bool:
    """Determine if the user message is an action (write) vs a query (read)."""
    if route in _ALWAYS_ACTION:
        return True
    if route in _ALWAYS_QUERY:
        return False
    # For ambiguous routes, use pattern matching
    has_action = bool(ACTION_PATTERNS.search(text))
    has_query = bool(QUERY_PATTERNS.search(text))
    if has_action and not has_query:
        return True
    if has_query and not has_action:
        return False
    # Both patterns matched: default to query (safer — don't create side effects)
    # Neither matched: default to not action
    return False


def is_delete_intent(text: str) -> bool:
    """Check if the user message expresses a delete/remove/cancel intent.
    Only these actions require confirmation; all other side-effects execute directly."""
    return bool(DELETE_PATTERNS.search(text))


# --- Confirmation message builder ---

_ACTION_LABELS = {
    "Expense": "مصروف",
    "Debt": "دين",
    "DebtPayment": "سداد دين",
    "Reminder": "تذكير",
    "Item": "غرض في المخزون",
    "ItemUsage": "استخدام غرض",
    "ItemMove": "نقل غرض",
}


def build_confirmation_message(action_type: str, entities: list[dict]) -> str:
    """Build Arabic confirmation message from extracted entities."""
    label = _ACTION_LABELS.get(action_type, "عملية")

    if not entities:
        return f"تبيني أسجل {label}؟"

    entity = entities[0]
    props = entity.get("properties", {})
    name = entity.get("entity_name", "")

    if action_type == "Expense":
        amount = props.get("amount", "")
        desc = name or props.get("description", "")
        currency = props.get("currency", "ريال")
        parts = [f"تبيني أسجل مصروف"]
        if desc:
            parts.append(f": {desc}")
        if amount:
            parts.append(f" بمبلغ {amount} {currency}")
        parts.append("؟")
        return "".join(parts)

    if action_type == "Debt":
        amount = props.get("amount", "")
        direction = props.get("direction", "")
        rels = entity.get("relationships", [])
        person = ""
        for r in rels:
            if r.get("target_type") == "Person":
                person = r.get("target_name", "")
                break
        direction_ar = "عليك" if direction == "i_owe" else "لك"
        parts = [f"تبيني أسجل دين"]
        if person:
            parts.append(f" مع {person}")
        if amount:
            parts.append(f" بمبلغ {amount}")
        if direction_ar:
            parts.append(f" ({direction_ar})")
        parts.append("؟")
        return "".join(parts)

    if action_type == "DebtPayment":
        amount = props.get("amount", "")
        rels = entity.get("relationships", [])
        person = ""
        for r in rels:
            if r.get("target_type") == "Person":
                person = r.get("target_name", "")
                break
        parts = [f"تبيني أسجل سداد"]
        if person:
            parts.append(f" من {person}")
        if amount:
            parts.append(f" بمبلغ {amount}")
        parts.append("؟")
        return "".join(parts)

    if action_type == "Reminder":
        parts = [f"تبيني أسجل تذكير"]
        if name:
            parts.append(f": {name}")
        due = props.get("due_date", "")
        if due:
            parts.append(f" (الموعد: {due})")
        parts.append("؟")
        return "".join(parts)

    if action_type == "Item":
        parts = ["تبيني أسجل غرض في المخزون"]
        if name:
            parts.append(f": {name}")
        qty = props.get("quantity", 1)
        if qty and qty > 1:
            parts.append(f" ({qty} حبة)")
        loc = props.get("location", "")
        if loc:
            parts.append(f" في {loc}")
        parts.append("؟")
        return "".join(parts)

    if action_type == "ItemUsage":
        parts = ["تبيني أنقص من المخزون"]
        if name:
            parts.append(f": {name}")
        qty = props.get("quantity_used", 1)
        if qty:
            parts.append(f" ({qty} حبة)")
        parts.append("؟")
        return "".join(parts)

    if action_type == "ItemMove":
        parts = ["تبيني أنقل"]
        if name:
            parts.append(f" {name}")
        from_loc = props.get("from_location", "")
        to_loc = props.get("to_location", "")
        if from_loc:
            parts.append(f" من {from_loc}")
        if to_loc:
            parts.append(f" إلى {to_loc}")
        parts.append("؟")
        return "".join(parts)

    return f"تبيني أسجل {label}: {name}؟"


# --- LLM prompts ---

CLARIFICATION_SYSTEM = """You check if a user message has enough information to perform an action.

Action requirements:
- Expense: needs amount (required), description is nice but optional
- Debt: needs person (required) and amount (required)
- DebtPayment: needs person (required) and amount (required)
- Reminder: needs title/description (required)
- Item: needs name (required), location is helpful but optional
- ItemUsage: needs item name (required) and quantity_used (default 1)
- ItemMove: needs item name (required) and to_location (required)

Respond in JSON:
{
  "complete": true/false,
  "missing_fields": ["field1", "field2"],
  "clarification_question_ar": "Arabic question asking for missing info"
}

If complete, return {"complete": true, "missing_fields": [], "clarification_question_ar": ""}
"""

CORE_MEMORY_SYSTEM = """Extract user preferences and patterns from the conversation.
Look for:
- Preferred currency
- Common contacts/people they interact with
- Spending patterns or categories
- Communication preferences (language mix, formality)
- Recurring topics or interests

Respond in JSON:
{
  "preferences": {
    "key": "value"
  }
}

Only include preferences you are confident about. If none found, return {"preferences": {}}
"""
