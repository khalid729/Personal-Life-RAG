"""
Open WebUI Filter for Personal Life RAG.
Version: 1.3

Injects the current date/time + user timezone into the system prompt
so that Open WebUI's LLM knows the correct date when presenting responses.

Copy this file's content into Open WebUI Admin → Functions → Add Function (type: Filter).

Changelog:
  v1.0 — Initial: date/time injection + anti-lying STATUS rules
  v1.1 — Added rule 7: auto store_document on file upload
  v1.2 — Rule 7: don't re-send file details to chat, don't use current time as appointment time
  v1.3 — Auto-detect file uploads → inject mandatory store_document instruction
"""

from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field


class Filter:
    """Personal Life RAG Filter v1.3 — Date/time injection + STATUS rules + auto file storage + file upload detection."""

    VERSION = "1.3"

    class Valves(BaseModel):
        timezone_offset_hours: int = Field(
            default=3,
            description="User timezone offset from UTC (e.g. 3 for Asia/Riyadh)",
        )
        prepend_date: bool = Field(
            default=True,
            description="Prepend current date/time to system prompt",
        )
        arabic_context: bool = Field(
            default=True,
            description="Add Arabic-specific instructions to system prompt",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _now(self) -> datetime:
        tz = timezone(timedelta(hours=self.valves.timezone_offset_hours))
        return datetime.now(tz)

    def _has_files(self, body: dict) -> bool:
        """Check if the request includes uploaded files."""
        # Check body-level files
        if body.get("files"):
            return True
        # Check message-level files/attachments
        messages = body.get("messages", [])
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            if msg.get("files") or msg.get("images"):
                return True
            # Open WebUI injects file content as context — check for citation markers
            content = msg.get("content", "")
            if "<source>" in content or "```" in content and len(content) > 500:
                return True
            break
        return False

    def inlet(self, body: dict, __user__: dict = {}) -> dict:
        """Modify request before it goes to the LLM."""
        if not self.valves.prepend_date:
            return body

        now = self._now()

        # Day names in Arabic
        day_names_ar = {
            0: "الإثنين",
            1: "الثلاثاء",
            2: "الأربعاء",
            3: "الخميس",
            4: "الجمعة",
            5: "السبت",
            6: "الأحد",
        }
        day_ar = day_names_ar.get(now.weekday(), "")

        # Month names in Arabic
        month_names_ar = {
            1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل",
            5: "مايو", 6: "يونيو", 7: "يوليو", 8: "أغسطس",
            9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
        }
        month_ar = month_names_ar.get(now.month, "")

        tomorrow = now + timedelta(days=1)
        tomorrow_ar = day_names_ar.get(tomorrow.weekday(), "")

        date_context = (
            f"التاريخ والوقت الحالي: {day_ar} {now.day} {month_ar} {now.year}، "
            f"الساعة {now.strftime('%H:%M')} (توقيت الرياض UTC+{self.valves.timezone_offset_hours})\n"
            f"بكرة = {tomorrow_ar} {tomorrow.day} {month_ar if tomorrow.month == now.month else month_names_ar.get(tomorrow.month, '')} {tomorrow.year}\n"
        )

        arabic_instructions = ""
        if self.valves.arabic_context:
            arabic_instructions = (
                "أنت مساعد شخصي متصل بنظام Personal Life RAG عبر أدوات (tools). "
                "الأدوات تتصل بالنظام وترجع بيانات حقيقية من قاعدة البيانات.\n\n"

                "=== قواعد صارمة يجب اتباعها ===\n"
                "1. عند عرض النتائج، اعرض البيانات كما هي بدون تعديل التواريخ أو الأرقام.\n"
                "2. رد دائماً بالعربي إلا لو المستخدم تكلم إنجليزي.\n"
                "3. كل رد من أداة chat يبدأ بواحد من هذه الحالات:\n"
                "   - 'STATUS: ACTION_EXECUTED' = الإجراء تم تنفيذه فعلاً. يمكنك إخبار المستخدم بالنتيجة.\n"
                "   - 'STATUS: PENDING_CONFIRMATION' = الإجراء لم يُنفّذ بعد. اعرض رسالة التأكيد واطلب 'نعم' أو 'لا'.\n"
                "   - 'STATUS: CONVERSATION' = رد محادثة عادي. لم يتم تعديل أي بيانات.\n\n"

                "4. ممنوع منعاً باتاً أن تقول 'تم' أو 'تمت' أو 'نجح' أو 'اكتمل' إلا إذا شفت 'STATUS: ACTION_EXECUTED'.\n"
                "5. لو المستخدم طلب إجراء (مسح، دمج، إضافة، تعديل) ورد الأداة 'STATUS: CONVERSATION'، "
                "قل للمستخدم بصراحة أن النظام لم ينفذ الإجراء المطلوب. لا تتظاهر أنه تم.\n"
                "6. لا تختلق نتائج أو تضيف معلومات غير موجودة في رد الأداة.\n"
                "7. عند رفع ملف (PDF، صورة، مستند):\n"
                "   أ) استخدم store_document لتخزين محتوى الملف — هذا يخزن النص ويستخرج كل الحقائق (مواعيد، أشخاص، تذكيرات) تلقائياً.\n"
                "   ب) أخبر المستخدم بالمعلومات المستخرجة من نتيجة store_document.\n"
                "   ج) إذا المستخدم أضاف تعليق إضافي (مثل 'ذكرني' أو 'السواق بيوديها')، أرسل تعليقه فقط عبر chat — بدون إعادة إرسال تفاصيل الملف.\n"
                "   ⚠️ لا تستخدم الوقت الحالي كوقت الموعد — استخدم فقط التواريخ والأوقات الموجودة في المستند.\n"
            )

        prefix = date_context + arabic_instructions

        # Detect file uploads — inject mandatory store_document instruction
        if self._has_files(body):
            file_instruction = (
                "\n\n🚨 تم رفع ملف! يجب عليك تنفيذ الخطوات التالية بالترتيب:\n"
                "1. استدعِ أداة store_document مع النص الكامل للملف — انسخ كل المحتوى كما هو بدون اختصار أو تلخيص.\n"
                "   ⚠️ لا ترسل ملخص — أرسل النص الكامل مع كل التواريخ والأوقات والأرقام والأسماء.\n"
                "2. اعرض للمستخدم المعلومات المستخرجة من نتيجة store_document.\n"
                "3. إذا المستخدم أضاف تعليق، أرسله عبر chat (بدون تفاصيل الملف).\n"
                "⛔ لا ترد على المستخدم بدون استدعاء store_document أولاً.\n"
            )
            prefix += file_instruction

        # Find or create system message
        messages = body.get("messages", [])
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = prefix + "\n" + messages[0]["content"]
        else:
            messages.insert(0, {"role": "system", "content": prefix})

        body["messages"] = messages
        return body

    def outlet(self, body: dict, __user__: dict = {}) -> dict:
        """Modify response after LLM generates it (no-op for now)."""
        return body
