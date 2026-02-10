AR_TO_EN_SYSTEM = """You are a translation assistant. Translate the following Saudi Arabic (عامية سعودية) text to English.
Keep proper nouns as-is. Preserve the meaning and intent accurately.
Output ONLY the English translation, nothing else."""

AR_TO_EN_EXAMPLES = [
    {"ar": "وش صرفت هالشهر على الأكل؟", "en": "How much did I spend this month on food?"},
    {"ar": "ذكرني أدفع الإيجار يوم ٢٥", "en": "Remind me to pay rent on the 25th"},
    {"ar": "مشروع التطبيق وصل وين؟", "en": "What's the status of the app project?"},
    {"ar": "أحمد يطلبني ٥٠٠ ريال", "en": "Ahmad owes me 500 SAR"},
    {"ar": "عندي فكرة عن بوت تيليقرام للمصاريف", "en": "I have an idea about a Telegram bot for expenses"},
]

EN_TO_AR_SYSTEM = """You are a translation assistant. Translate the following English text to Saudi Arabic (عامية سعودية).
Use natural colloquial Saudi dialect. Keep proper nouns as-is.
Output ONLY the Arabic translation, nothing else."""

EN_TO_AR_EXAMPLES = [
    {"en": "You spent 3200 SAR on food this month.", "ar": "صرفت ٣٢٠٠ ريال على الأكل هالشهر."},
    {"en": "I set a reminder for rent payment on the 25th.", "ar": "حطيت لك تذكير تدفع الإيجار يوم ٢٥."},
    {"en": "The app project is 60% complete.", "ar": "مشروع التطبيق وصل ٦٠٪ تقريباً."},
]


def build_translate_ar_to_en(text: str) -> list[dict]:
    messages = [{"role": "system", "content": AR_TO_EN_SYSTEM}]
    for ex in AR_TO_EN_EXAMPLES:
        messages.append({"role": "user", "content": ex["ar"]})
        messages.append({"role": "assistant", "content": ex["en"]})
    messages.append({"role": "user", "content": text})
    return messages


def build_translate_en_to_ar(text: str) -> list[dict]:
    messages = [{"role": "system", "content": EN_TO_AR_SYSTEM}]
    for ex in EN_TO_AR_EXAMPLES:
        messages.append({"role": "user", "content": ex["en"]})
        messages.append({"role": "assistant", "content": ex["ar"]})
    messages.append({"role": "user", "content": text})
    return messages
