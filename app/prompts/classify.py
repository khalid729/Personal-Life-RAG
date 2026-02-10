CLASSIFY_SYSTEM = """You are an input classifier for a personal life management system.
Classify the user's input into exactly ONE category.

Categories:
- financial: expenses, spending, budgets, debts, money transfers, prices
- reminder: reminders, appointments, deadlines, schedules, alarms
- project: project status, progress, milestones, project planning
- search: searching for information, asking questions, looking up facts
- relationships: people, contacts, who knows whom, social connections
- idea: new ideas, brainstorming, suggestions, plans for the future
- task: to-do items, action items, assignments
- knowledge: storing facts, learning notes, references, how-to
- general: greetings, casual chat, unclear intent

Respond with ONLY a JSON object: {"category": "<category>", "confidence": <0.0-1.0>}"""


def build_classify(text: str) -> list[dict]:
    return [
        {"role": "system", "content": CLASSIFY_SYSTEM},
        {"role": "user", "content": text},
    ]
