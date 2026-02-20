"""Tool-calling chat service.

The LLM calls tools → code executes and returns REAL results → LLM formats
response from facts. The model *cannot* lie because it sees the actual outcome.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.prompts.tool_system import build_tool_system_prompt

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_reminders",
            "description": "ابحث عن التذكيرات. استخدمها لما المستخدم يسأل عن تذكيراته أو مواعيده.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done", "snoozed", "all"],
                        "description": "فلتر حسب الحالة. الافتراضي: pending",
                    },
                    "query": {
                        "type": "string",
                        "description": "بحث بالعنوان (اختياري). إذا حُدد، يبحث عن تذكيرات تطابق هذا النص.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "أنشئ تذكير جديد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "عنوان التذكير بالعربي"},
                    "due_date": {"type": "string", "description": "تاريخ الاستحقاق YYYY-MM-DD"},
                    "time": {"type": "string", "description": "الوقت HH:MM (24h)"},
                    "recurrence": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly", "yearly"],
                    },
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "احذف تذكير. يبحث بطريقة ذكية (مو لازم العنوان بالضبط). اكتب وصف واضح ومفصل للتذكير عشان يلقاه.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "وصف التذكير المراد حذفه — اكتب أكثر تفاصيل ممكنة مثل: استرداد العربون من محل الورق الجداري"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "سجّل مصروف جديد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "وصف المصروف"},
                    "amount": {"type": "number", "description": "المبلغ بالريال"},
                    "category": {"type": "string", "description": "التصنيف (طعام، مواصلات، ترفيه، إلخ)"},
                    "date": {"type": "string", "description": "التاريخ YYYY-MM-DD (الافتراضي: اليوم)"},
                    "vendor": {"type": "string", "description": "المتجر أو الجهة"},
                },
                "required": ["description", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_plan",
            "description": "اعرض خطة اليوم: التذكيرات والمهام والديون.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "ابحث في الذاكرة والمعرفة المخزنة. استخدمها لما المستخدم يسأل عن معلومات أو أشخاص أو مواضيع.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "سؤال البحث"},
                },
                "required": ["query"],
            },
        },
    },
    # --- Phase 1: Financial + Reminder Completion ---
    {
        "type": "function",
        "function": {
            "name": "update_reminder",
            "description": "عدّل أو أنجز أو أجّل أو ألغِ تذكير موجود. استخدمها لما المستخدم يقول خلصت/أنجزت/أجّل/ألغي/عدّل تذكير.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "وصف التذكير المراد تعديله — اكتب أكثر تفاصيل ممكنة"},
                    "action": {
                        "type": "string",
                        "enum": ["update", "done", "snooze", "cancel"],
                        "description": "نوع الإجراء: update=تعديل، done=إنجاز، snooze=تأجيل، cancel=إلغاء",
                    },
                    "due_date": {"type": "string", "description": "تاريخ جديد YYYY-MM-DD (للتعديل أو التأجيل)"},
                    "time": {"type": "string", "description": "وقت جديد HH:MM (24h)"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["query", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expense_report",
            "description": "تقرير المصاريف الشهري مع تفصيل حسب الفئة. استخدمها لما يسأل عن مصاريفه أو كم صرف.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "minimum": 1, "maximum": 12, "description": "رقم الشهر (الافتراضي: الشهر الحالي)"},
                    "year": {"type": "integer", "description": "السنة (الافتراضي: السنة الحالية)"},
                    "compare": {"type": "boolean", "description": "قارن مع الشهر السابق"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_debt_summary",
            "description": "ملخص الديون: كم تطلب وكم عليك. استخدمها لما يسأل عن الديون.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_debt",
            "description": "سجّل دين جديد (لك أو عليك).",
            "parameters": {
                "type": "object",
                "properties": {
                    "person": {"type": "string", "description": "اسم الشخص"},
                    "amount": {"type": "number", "description": "المبلغ بالريال"},
                    "direction": {
                        "type": "string",
                        "enum": ["i_owe", "owed_to_me"],
                        "description": "i_owe=عليّ، owed_to_me=لي عنده",
                    },
                    "reason": {"type": "string", "description": "سبب الدين"},
                },
                "required": ["person", "amount", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pay_debt",
            "description": "سجّل سداد دين (كلي أو جزئي).",
            "parameters": {
                "type": "object",
                "properties": {
                    "person": {"type": "string", "description": "اسم الشخص"},
                    "amount": {"type": "number", "description": "المبلغ المسدد بالريال"},
                    "direction": {
                        "type": "string",
                        "enum": ["i_owe", "owed_to_me"],
                        "description": "اتجاه الدين (اختياري — يُحدد تلقائياً لو في دين واحد)",
                    },
                },
                "required": ["person", "amount"],
            },
        },
    },
    # --- Phase 2: Knowledge + People ---
    {
        "type": "function",
        "function": {
            "name": "store_note",
            "description": "احفظ معلومة أو ملاحظة في الذاكرة. استخدمها لما المستخدم يطلب صراحةً تخزين شيء معيّن.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "النص المراد حفظه"},
                    "topic": {"type": "string", "description": "الموضوع (اختياري)"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_person_info",
            "description": "اعرض معلومات شخص معيّن. استخدمها لما يسأل عن شخص بالاسم.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "اسم الشخص"},
                },
                "required": ["name"],
            },
        },
    },
    # --- Phase 3: Inventory + Productivity ---
    {
        "type": "function",
        "function": {
            "name": "manage_inventory",
            "description": "إدارة المخزون: بحث، إضافة، نقل، استخدام أغراض أو تقرير عام.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "add", "move", "use", "report"],
                        "description": "search=بحث، add=إضافة، move=نقل، use=استخدام (إنقاص الكمية)، report=تقرير",
                    },
                    "name": {"type": "string", "description": "اسم الغرض"},
                    "quantity": {"type": "integer", "description": "الكمية"},
                    "location": {"type": "string", "description": "الموقع (مكان التخزين أو النقل إليه)"},
                    "category": {"type": "string", "description": "التصنيف"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_tasks",
            "description": "إدارة المهام: عرض، إنشاء، تعديل، أو حذف مهمة.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "create", "update", "delete"],
                        "description": "list=عرض، create=إنشاء، update=تعديل، delete=حذف",
                    },
                    "title": {"type": "string", "description": "عنوان المهمة"},
                    "status": {"type": "string", "enum": ["todo", "in_progress", "done"], "description": "حالة المهمة"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "project": {"type": "string", "description": "المشروع المرتبط"},
                    "due_date": {"type": "string", "description": "تاريخ الاستحقاق YYYY-MM-DD"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_projects",
            "description": "إدارة المشاريع: عرض، تفاصيل، إنشاء (مع مراحل)، تعديل، حذف، تركيز، أقسام ومراحل. لا تستخدمها للدمج — استخدم merge_projects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "create", "update", "delete", "focus", "unfocus",
                                 "add_section", "update_section", "delete_section", "assign_section", "set_phase"],
                        "description": "list=عرض الكل، get=تفاصيل، create=إنشاء، update=تعديل، delete=حذف، focus=تركيز، unfocus=إلغاء التركيز، add_section=إضافة قسم، update_section=تعديل قسم، delete_section=حذف قسم، assign_section=ربط عنصر بقسم، set_phase=تحديد المرحلة النشطة",
                    },
                    "name": {"type": "string", "description": "اسم المشروع"},
                    "status": {"type": "string", "description": "حالة المشروع (active, completed, on_hold, cancelled)"},
                    "description": {"type": "string", "description": "وصف المشروع"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "أسماء بديلة للمشروع (عربي/إنجليزي مختصرة)",
                    },
                    "section_name": {"type": "string", "description": "اسم القسم أو المرحلة"},
                    "section_type": {"type": "string", "enum": ["topic", "phase"], "description": "نوع القسم: topic=موضوع, phase=مرحلة"},
                    "order": {"type": "integer", "description": "ترتيب القسم (للمراحل)"},
                    "entity_type": {"type": "string", "description": "نوع العنصر المراد ربطه بالقسم (Task, Knowledge, etc.)"},
                    "entity_name": {"type": "string", "description": "اسم العنصر المراد ربطه بالقسم"},
                    "with_phases": {"type": "boolean", "description": "إنشاء المشروع مع مراحل افتراضية (Planning, Preparation, Execution, Review)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_lists",
            "description": "إدارة القوائم: قائمة بقالة، مشتريات، أفكار، إلخ. إنشاء، إضافة عناصر، تعليم كمنجز، حذف.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "create", "add_entry", "check_entry", "uncheck_entry", "remove_entry", "delete"],
                        "description": "list=عرض كل القوائم، get=تفاصيل قائمة، create=إنشاء، add_entry=إضافة عنصر، check_entry=تعليم كمنجز، uncheck_entry=إلغاء التعليم، remove_entry=حذف عنصر، delete=حذف القائمة",
                    },
                    "name": {"type": "string", "description": "اسم القائمة"},
                    "list_type": {"type": "string", "enum": ["shopping", "ideas", "checklist", "reference"], "description": "نوع القائمة"},
                    "entry": {"type": "string", "description": "محتوى العنصر"},
                    "entries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "عناصر متعددة للإضافة دفعة وحدة",
                    },
                    "project": {"type": "string", "description": "ربط القائمة بمشروع (اختياري)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_projects",
            "description": "ادمج مشاريع مكررة في مشروع واحد. ينقل كل المهام للمشروع الهدف ويحذف المشاريع القديمة.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {"type": "string", "description": "اسم المشروع الهدف اللي تبي تدمج فيه"},
                    "source_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "أسماء المشاريع المراد دمجها وحذفها",
                    },
                },
                "required": ["target_name", "source_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_productivity_stats",
            "description": "إحصائيات الإنتاجية: جلسات التركيز، السبرنتات، أو نظرة عامة.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["focus", "sprint", "overview"],
                        "description": "focus=جلسات التركيز، sprint=السبرنتات، overview=نظرة عامة (الافتراضي)",
                    },
                },
                "required": [],
            },
        },
    },
]


def _now() -> str:
    tz = timezone(timedelta(hours=settings.timezone_offset_hours))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ToolCallingService:
    """Orchestrates tool-calling chat: LLM picks tools → code executes → LLM responds."""

    MAX_ITERATIONS = 3

    def __init__(self, llm, graph, vector, memory, ner=None):
        self.llm = llm
        self.graph = graph
        self.vector = vector
        self.memory = memory
        self.ner = ner

        self._TOOL_HANDLERS = {
            "search_reminders": self._handle_search_reminders,
            "create_reminder": self._handle_create_reminder,
            "delete_reminder": self._handle_delete_reminder,
            "add_expense": self._handle_add_expense,
            "get_daily_plan": self._handle_get_daily_plan,
            "search_knowledge": self._handle_search_knowledge,
            # Phase 1
            "update_reminder": self._handle_update_reminder,
            "get_expense_report": self._handle_get_expense_report,
            "get_debt_summary": self._handle_get_debt_summary,
            "record_debt": self._handle_record_debt,
            "pay_debt": self._handle_pay_debt,
            # Phase 2
            "store_note": self._handle_store_note,
            "get_person_info": self._handle_get_person_info,
            # Phase 3
            "manage_inventory": self._handle_manage_inventory,
            "manage_tasks": self._handle_manage_tasks,
            "manage_projects": self._handle_manage_projects,
            "manage_lists": self._handle_manage_lists,
            "merge_projects": self._handle_merge_projects,
            "get_productivity_stats": self._handle_get_productivity_stats,
        }

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    async def _handle_search_reminders(self, status: str = "pending", query: str | None = None) -> dict:
        if query:
            status_filter = f"['{status}']" if status and status != "all" else ""
            matches = await self.graph._find_matching_reminders(query, status_filter=status_filter)
            if not matches:
                return {"reminders": f"لا توجد تذكيرات تطابق '{query}'"}
            lines = [f"  - {r[0]}" for r in matches]
            return {"reminders": "\n".join(lines)}
        if status == "all":
            status = None
        text = await self.graph.query_reminders(status=status)
        return {"reminders": text}

    async def _handle_create_reminder(
        self, title: str, due_date: str | None = None,
        time: str | None = None, recurrence: str | None = None,
        priority: int | None = None,
    ) -> dict:
        props = {}
        if due_date:
            props["due_date"] = due_date
        if time:
            props["time"] = time
        if recurrence:
            props["recurrence"] = recurrence
        if priority is not None:
            props["priority"] = priority
        await self.graph.create_reminder(title, **props)
        return {"status": "created", "title": title, **props}

    # Strip parenthetical decoration the model adds, e.g. "(متأخرة)" "(مكتمل)"
    _PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")

    async def _handle_delete_reminder(self, query: str) -> dict:
        # Clean query: strip parenthetical text like (متأخرة)
        cleaned = self._PAREN_RE.sub(" ", query).strip()

        # Try direct graph matching first (handles same-language matches)
        result = await self.graph.update_reminder_status(cleaned, action="delete")
        if "error" not in result:
            return result

        # If failed and original query differs, retry with original
        if cleaned != query:
            result = await self.graph.update_reminder_status(query, action="delete")
            if "error" not in result:
                return result

        # Cross-language fallback: find best match via vector similarity
        # (handles Arabic query vs English stored title)
        best_title = await self._vector_match_reminder(cleaned)
        if best_title:
            result = await self.graph.update_reminder_status(best_title, action="delete")
            if "error" not in result:
                return result

        return {"error": f"No reminder found matching '{query}'"}

    async def _vector_match_reminder(self, query: str) -> str | None:
        """Find best matching reminder title via vector similarity (cross-language)."""
        try:
            # Get all pending reminders
            reminders_text = await self.graph.query_reminders(status="pending")
            if not reminders_text or reminders_text == "No reminders found.":
                return None

            # Extract titles from the formatted text
            titles = []
            for line in reminders_text.split("\n"):
                line = line.strip().lstrip("- ")
                if not line or line.startswith("⚠") or line.startswith("Upcoming") or line.startswith("Snoozed"):
                    continue
                # Title is everything before " (due:" or " [priority:"
                for sep in [" (due:", " [priority:", " [recurring"]:
                    if sep in line:
                        line = line[:line.index(sep)]
                        break
                if line:
                    titles.append(line.strip())

            if not titles:
                return None

            # Embed query + all titles, find best cosine match
            all_texts = [query] + titles
            vectors = self.vector.embed(all_texts)
            query_vec = vectors[0]

            best_score = 0.0
            best_title = None
            for i, title in enumerate(titles):
                # Cosine similarity
                dot = sum(a * b for a, b in zip(query_vec, vectors[i + 1]))
                norm_q = sum(a * a for a in query_vec) ** 0.5
                norm_t = sum(a * a for a in vectors[i + 1]) ** 0.5
                score = dot / (norm_q * norm_t) if norm_q * norm_t > 0 else 0
                if score > best_score:
                    best_score = score
                    best_title = title

            if best_score >= 0.40:
                logger.info("Vector matched reminder '%s' (score=%.3f) for query '%s'",
                            best_title, best_score, query)
                return best_title

            logger.info("Vector match best: '%s' (score=%.3f) for query '%s' — below threshold",
                        best_title, best_score, query)
            return None
        except Exception as e:
            logger.warning("Vector reminder matching failed: %s", e)
            return None

    async def _handle_add_expense(
        self, description: str, amount: float,
        category: str | None = None, date: str | None = None,
        vendor: str | None = None,
    ) -> dict:
        props = {}
        if category:
            props["category"] = category
        if date:
            props["date"] = date
        if vendor:
            props["vendor"] = vendor
        await self.graph.create_expense(description, amount, **props)
        return {"status": "created", "description": description, "amount": amount, **props}

    async def _handle_get_daily_plan(self) -> dict:
        text = await self.graph.query_daily_plan()
        return {"plan": text}

    async def _handle_search_knowledge(self, query: str) -> dict:
        vector_results, graph_results, section_results = await asyncio.gather(
            self.vector.search(query, limit=5),
            self.graph.search_nodes(query, limit=10),
            self.graph.search_sections(query, limit=15),
        )
        parts = []
        if section_results:
            parts.append(section_results)
        if graph_results:
            parts.append(graph_results)
        if vector_results:
            for r in vector_results:
                text = r.get("text", r.get("payload", {}).get("text", ""))
                if text:
                    parts.append(text)
        return {"results": "\n\n".join(parts) if parts else "لا توجد نتائج."}

    # --- Phase 1 handlers ---

    async def _handle_update_reminder(
        self, query: str, action: str,
        due_date: str | None = None, time: str | None = None,
        priority: int | None = None,
    ) -> dict:
        cleaned = self._PAREN_RE.sub(" ", query).strip()

        if action in ("done", "snooze", "cancel"):
            snooze_until = due_date if action == "snooze" else None
            result = await self.graph.update_reminder_status(cleaned, action=action, snooze_until=snooze_until)
            if "error" in result:
                # Cross-language fallback via vector
                best_title = await self._vector_match_reminder(cleaned)
                if best_title:
                    result = await self.graph.update_reminder_status(best_title, action=action, snooze_until=snooze_until)
            return result

        # action == "update"
        kwargs = {}
        if due_date:
            kwargs["due_date"] = due_date
        if time:
            kwargs["due_date"] = f"{due_date or ''}T{time}" if due_date else None
            if not kwargs.get("due_date"):
                # time-only update: keep existing date, just add time
                pass
        if priority is not None:
            kwargs["priority"] = priority
        if not kwargs:
            return {"error": "No fields to update"}

        result = await self.graph.update_reminder(cleaned, **kwargs)
        if "error" in result:
            best_title = await self._vector_match_reminder(cleaned)
            if best_title:
                result = await self.graph.update_reminder(best_title, **kwargs)
        return result

    async def _handle_get_expense_report(
        self, month: int | None = None, year: int | None = None,
        compare: bool = False,
    ) -> dict:
        tz = timezone(timedelta(hours=settings.timezone_offset_hours))
        now = datetime.now(tz)
        m = month or now.month
        y = year or now.year
        if compare:
            return await self.graph.query_month_comparison(m, y)
        return await self.graph.query_monthly_report(m, y)

    async def _handle_get_debt_summary(self) -> dict:
        return await self.graph.query_debt_summary()

    async def _handle_record_debt(
        self, person: str, amount: float, direction: str,
        reason: str | None = None,
    ) -> dict:
        props = {}
        if reason:
            props["reason"] = reason
        await self.graph.upsert_debt(person, amount, direction, **props)
        return {"status": "created", "person": person, "amount": amount, "direction": direction, **props}

    async def _handle_pay_debt(
        self, person: str, amount: float, direction: str | None = None,
    ) -> dict:
        return await self.graph.record_debt_payment(person, amount, direction=direction)

    # --- Phase 2 handlers ---

    async def _handle_store_note(self, text: str, topic: str | None = None) -> dict:
        try:
            # NER on original text
            ner_hints = ""
            if self.ner:
                entities = self.ner.extract_entities(text)
                ner_hints = self.ner.format_hints(entities)

            # Translate to English for extraction
            text_en = await self.llm.translate_to_english(text)

            # Extract structured facts
            facts = await self.llm.extract_facts_specialized(text_en, "general", ner_hints=ner_hints)

            upserted = 0
            if facts.get("entities"):
                upserted = await self.graph.upsert_from_facts(facts)

            # Also store in vector
            meta = {"source_type": "note", "topic": topic or "general"}
            await self.vector.upsert_chunks([text], [meta])

            return {"status": "stored", "entities_saved": upserted, "text_preview": text[:100]}
        except Exception as e:
            logger.exception("store_note failed")
            return {"error": str(e)}

    async def _handle_get_person_info(self, name: str) -> dict:
        context = await self.graph.query_person_context(name)
        return {"info": context if context else f"لا توجد معلومات عن '{name}'."}

    # --- Phase 3 handlers ---

    async def _handle_manage_inventory(
        self, action: str, name: str | None = None,
        quantity: int | None = None, location: str | None = None,
        category: str | None = None,
    ) -> dict:
        if action == "search":
            text = await self.graph.query_inventory(search=name, category=category)
            return {"results": text}

        if action == "report":
            return await self.graph.query_inventory_report()

        if action == "add":
            if not name:
                return {"error": "اسم الغرض مطلوب"}
            props = {}
            if quantity is not None:
                props["quantity"] = quantity
            if location:
                props["location"] = location
            if category:
                props["category"] = category
            return await self.graph.upsert_item(name, **props)

        if action == "move":
            if not name or not location:
                return {"error": "اسم الغرض والموقع الجديد مطلوبين"}
            return await self.graph.move_item(name, to_location=location)

        if action == "use":
            if not name:
                return {"error": "اسم الغرض مطلوب"}
            delta = -(quantity or 1)
            return await self.graph.adjust_item_quantity(name, delta)

        return {"error": f"Unknown action: {action}"}

    async def _handle_manage_tasks(
        self, action: str, title: str | None = None,
        status: str | None = None, priority: int | None = None,
        project: str | None = None, due_date: str | None = None,
    ) -> dict:
        if action == "list":
            text = await self.graph.query_active_tasks(status_filter=status)
            return {"tasks": text}

        if action == "create":
            if not title:
                return {"error": "عنوان المهمة مطلوب"}
            props = {}
            if status:
                props["status"] = status
            if priority is not None:
                props["priority"] = priority
            if due_date:
                props["due_date"] = due_date
            await self.graph.upsert_task(title, **props)
            if project:
                await self.graph.upsert_project(project)
                try:
                    await self.graph.create_relationship(
                        "Task", "title", title,
                        "BELONGS_TO", "Project", "name", project,
                    )
                except Exception:
                    pass
            return {"status": "created", "title": title, "project": project}

        if action == "update":
            if not title:
                return {"error": "عنوان المهمة مطلوب"}
            return await self.graph.update_task_direct(
                title, status=status, priority=priority,
                due_date=due_date, project=project,
            )

        if action == "delete":
            if not title:
                return {"error": "عنوان المهمة مطلوب"}
            return await self.graph.delete_task(title)

        return {"error": f"Unknown action: {action}"}

    async def _handle_manage_projects(
        self, action: str, name: str | None = None,
        status: str | None = None, description: str | None = None,
        priority: int | None = None, aliases: list[str] | None = None,
        section_name: str | None = None, section_type: str | None = None,
        order: int | None = None, entity_type: str | None = None,
        entity_name: str | None = None, with_phases: bool = False,
        _session_id: str | None = None,
    ) -> dict:
        if action == "list":
            text = await self.graph.query_projects_overview(status_filter=status)
            return {"projects": text}

        if action == "get":
            if not name:
                return {"error": "اسم المشروع مطلوب"}
            text = await self.graph.query_project_details(name)
            return {"projects": text}

        if action == "create":
            if not name:
                return {"error": "اسم المشروع مطلوب"}
            props = {}
            if status:
                props["status"] = status
            if description:
                props["description"] = description
            if priority is not None:
                props["priority"] = priority
            if with_phases:
                result = await self.graph.create_project_with_phases(name, **props)
                if aliases:
                    await self.graph.set_project_aliases(name, aliases)
                    await self.graph.register_aliases_in_vector(name, aliases)
                result["aliases"] = aliases or []
                return result
            await self.graph.upsert_project(name, **props)
            if aliases:
                await self.graph.set_project_aliases(name, aliases)
                await self.graph.register_aliases_in_vector(name, aliases)
            return {"status": "created", "name": name, "aliases": aliases or [], **props}

        if action == "update":
            if not name:
                return {"error": "اسم المشروع مطلوب"}
            props = {}
            if status:
                props["status"] = status
            if description:
                props["description"] = description
            if priority is not None:
                props["priority"] = priority
            if aliases:
                await self.graph.set_project_aliases(name, aliases)
                await self.graph.register_aliases_in_vector(name, aliases)
            if not props and not aliases:
                return {"error": "لا توجد حقول للتعديل"}
            if props:
                await self.graph.upsert_project(name, **props)
            return {"status": "updated", "name": name, "aliases": aliases or [], **props}

        if action == "delete":
            if not name:
                return {"error": "اسم المشروع مطلوب"}
            return await self.graph.delete_project(name)

        if action == "focus":
            if not name:
                return {"error": "اسم المشروع مطلوب"}
            resolved = await self.graph.resolve_entity_name(name, "Project")
            # Verify project exists
            details = await self.graph.query_project_details(resolved)
            if details.startswith("No project found"):
                return {"error": f"ما لقيت مشروع باسم '{name}'"}
            if _session_id:
                await self.memory.set_active_project(_session_id, resolved)
            return {"status": "focused", "name": resolved}

        if action == "unfocus":
            if _session_id:
                await self.memory.clear_active_project(_session_id)
            return {"status": "unfocused"}

        if action == "add_section":
            if not name or not section_name:
                return {"error": "اسم المشروع والقسم مطلوبين"}
            props = {}
            if section_type:
                props["section_type"] = section_type
            if order is not None:
                props["order"] = order
            return await self.graph.create_section(name, section_name, **props)

        if action == "update_section":
            if not name or not section_name:
                return {"error": "اسم المشروع والقسم مطلوبين"}
            props = {}
            if description:
                props["description"] = description
            if status:
                props["status"] = status
            if order is not None:
                props["order"] = order
            return await self.graph.update_section(name, section_name, **props)

        if action == "delete_section":
            if not name or not section_name:
                return {"error": "اسم المشروع والقسم مطلوبين"}
            return await self.graph.delete_section(name, section_name)

        if action == "assign_section":
            if not name or not section_name or not entity_type or not entity_name:
                return {"error": "اسم المشروع والقسم ونوع واسم العنصر مطلوبين"}
            return await self.graph.assign_to_section(name, section_name, entity_type, entity_name)

        if action == "set_phase":
            if not name or not section_name:
                return {"error": "اسم المشروع والمرحلة مطلوبين"}
            return await self.graph.set_active_phase(name, section_name)

        return {"error": f"Unknown action: {action}"}

    async def _handle_manage_lists(
        self, action: str, name: str | None = None,
        list_type: str | None = None, entry: str | None = None,
        entries: list[str] | None = None, project: str | None = None,
    ) -> dict:
        if action == "list":
            text = await self.graph.query_lists_overview(project_name=project)
            return {"lists": text}

        if action == "get":
            if not name:
                return {"error": "اسم القائمة مطلوب"}
            text = await self.graph.query_list(name)
            return {"list": text}

        if action == "create":
            if not name:
                return {"error": "اسم القائمة مطلوب"}
            return await self.graph.create_list(name, list_type=list_type or "checklist", project_name=project)

        if action == "add_entry":
            if not name:
                return {"error": "اسم القائمة مطلوب"}
            if entries:
                for e in entries:
                    await self.graph.add_list_entry(name, e)
                return {"status": "added", "list": name, "entries_added": len(entries)}
            if not entry:
                return {"error": "محتوى العنصر مطلوب"}
            return await self.graph.add_list_entry(name, entry)

        if action == "check_entry":
            if not name or not entry:
                return {"error": "اسم القائمة والعنصر مطلوبين"}
            return await self.graph.check_list_entry(name, entry, checked=True)

        if action == "uncheck_entry":
            if not name or not entry:
                return {"error": "اسم القائمة والعنصر مطلوبين"}
            return await self.graph.check_list_entry(name, entry, checked=False)

        if action == "remove_entry":
            if not name or not entry:
                return {"error": "اسم القائمة والعنصر مطلوبين"}
            return await self.graph.remove_list_entry(name, entry)

        if action == "delete":
            if not name:
                return {"error": "اسم القائمة مطلوب"}
            return await self.graph.delete_list(name)

        return {"error": f"Unknown action: {action}"}

    async def _handle_merge_projects(
        self, target_name: str, source_names: list[str],
    ) -> dict:
        return await self.graph.merge_projects(source_names, target_name)

    async def _handle_get_productivity_stats(self, type: str | None = None) -> dict:
        stat_type = type or "overview"
        if stat_type == "focus":
            return await self.graph.query_focus_stats()
        if stat_type == "sprint":
            sprints = await self.graph.query_sprints()
            return {"sprints": sprints}
        # overview: combine focus + tasks + projects
        focus = await self.graph.query_focus_stats()
        tasks_text = await self.graph.query_active_tasks()
        projects_text = await self.graph.query_projects_overview()
        return {
            "focus": focus,
            "active_tasks": tasks_text,
            "projects": projects_text,
        }

    # ------------------------------------------------------------------
    # Tool executor with validation wrapper
    # ------------------------------------------------------------------

    _SESSION_AWARE_TOOLS = {"manage_projects"}

    async def _execute_tool(self, name: str, arguments: dict, session_id: str | None = None) -> dict:
        """Execute a tool and return validated result."""
        handler = self._TOOL_HANDLERS.get(name)
        if not handler:
            return {"tool": name, "success": False, "error": f"Unknown tool: {name}", "executed_at": _now()}
        try:
            if session_id and name in self._SESSION_AWARE_TOOLS:
                arguments = {**arguments, "_session_id": session_id}
            result = await handler(**arguments)
            success = "error" not in result if isinstance(result, dict) else True
            return {"tool": name, "success": success, "data": result, "executed_at": _now()}
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return {"tool": name, "success": False, "error": str(e), "executed_at": _now()}

    # ------------------------------------------------------------------
    # Main chat loop
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_reply(tool_results: list[dict]) -> str:
        """Generate a simple Arabic reply from tool results when LLM times out."""
        parts = []
        for r in tool_results:
            tool = r.get("tool", "")
            if r.get("success"):
                data = r.get("data", {})
                if tool == "create_reminder":
                    parts.append(f"تم إنشاء تذكير: {data.get('title', '')}")
                elif tool == "delete_reminder":
                    parts.append(f"تم حذف تذكير: {data.get('title', '')}")
                elif tool == "add_expense":
                    parts.append(f"تم تسجيل مصروف: {data.get('description', '')} ({data.get('amount', '')} ريال)")
                elif tool == "search_reminders":
                    parts.append(data.get("reminders", ""))
                elif tool == "get_daily_plan":
                    parts.append(data.get("plan", ""))
                elif tool == "search_knowledge":
                    parts.append(data.get("results", ""))
                elif tool == "update_reminder":
                    parts.append(f"تم تحديث تذكير: {data.get('title', '')}")
                elif tool == "get_expense_report":
                    total = data.get("total", 0)
                    parts.append(f"إجمالي المصاريف: {total:.0f} ريال")
                elif tool == "get_debt_summary":
                    parts.append(f"عليك: {data.get('total_i_owe', 0):.0f} ريال | لك: {data.get('total_owed_to_me', 0):.0f} ريال")
                elif tool == "record_debt":
                    parts.append(f"تم تسجيل دين: {data.get('person', '')} ({data.get('amount', '')} ريال)")
                elif tool == "pay_debt":
                    parts.append(f"تم تسجيل سداد: {data.get('person', '')}")
                elif tool == "store_note":
                    parts.append(f"تم حفظ الملاحظة ({data.get('entities_saved', 0)} عنصر)")
                elif tool == "get_person_info":
                    parts.append(data.get("info", ""))
                elif tool == "manage_inventory":
                    parts.append(data.get("results", str(data)))
                elif tool == "manage_tasks":
                    parts.append(data.get("tasks", str(data)))
                elif tool == "manage_projects":
                    if data.get("status") == "focused":
                        parts.append(f"تم التركيز على مشروع: {data.get('name', '')}")
                    elif data.get("status") == "unfocused":
                        parts.append("تم إلغاء التركيز على المشروع")
                    else:
                        parts.append(data.get("projects", str(data)))
                elif tool == "manage_lists":
                    if data.get("list"):
                        parts.append(data["list"])
                    elif data.get("lists"):
                        parts.append(data["lists"])
                    else:
                        parts.append(str(data))
                elif tool == "merge_projects":
                    parts.append(f"تم دمج {data.get('sources_deleted', 0)} مشاريع ونقل {data.get('tasks_moved', 0)} مهام إلى {data.get('target', '')}")
                elif tool == "get_productivity_stats":
                    parts.append(str(data))
                else:
                    parts.append(f"تم تنفيذ {tool}")
            else:
                parts.append(f"فشل {tool}: {r.get('error', r.get('data', {}).get('error', ''))}")
        return "\n".join(parts) if parts else "تم تنفيذ الطلب."

    async def chat(self, message: str, session_id: str = "default") -> dict:
        """Non-streaming tool-calling chat."""
        # 1. Build system prompt
        memory_context = await self.memory.build_system_memory_context(session_id)
        active_project = await self.memory.get_active_project(session_id)
        system_prompt = build_tool_system_prompt(memory_context, active_project=active_project)

        # 2. Load conversation history
        history = await self.memory.get_working_memory(session_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        # Track new turns added during tool-calling (for working memory storage)
        new_turns: list[dict] = []

        # 3. Tool calling loop (parallel tool execution)
        tool_results = []
        response = {}
        for i in range(self.MAX_ITERATIONS):
            try:
                response = await self.llm.chat_with_tools(messages, tools=TOOLS)
            except Exception as e:
                logger.error("LLM call failed (iteration %d): %s", i, e)
                if tool_results:
                    return {
                        "reply": self._fallback_reply(tool_results),
                        "tool_calls": tool_results,
                        "route": "tool_calling",
                    }
                return {"reply": "عذراً، حصل خطأ في المعالجة. حاول مرة ثانية.", "tool_calls": [], "route": "tool_calling"}

            tool_calls = response.get("tool_calls")
            if not tool_calls:
                break  # Final text response

            # Execute all tool calls in parallel
            parsed_calls = []
            for tc in tool_calls:
                raw_args = tc["function"]["arguments"]
                args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else (raw_args if isinstance(raw_args, dict) else {})
                parsed_calls.append((tc, args))

            results = await asyncio.gather(
                *(self._execute_tool(tc["function"]["name"], args, session_id=session_id) for tc, args in parsed_calls),
                return_exceptions=True,
            )

            # Build messages: one assistant message with all tool_calls, then individual tool results
            assistant_tc_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            }
            messages.append(assistant_tc_msg)
            new_turns.append(assistant_tc_msg)

            for (tc, _), result in zip(parsed_calls, results):
                if isinstance(result, Exception):
                    result = {"tool": tc["function"]["name"], "success": False, "error": str(result), "executed_at": _now()}
                tool_results.append(result)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
                messages.append(tool_msg)
                new_turns.append(tool_msg)

        reply = response.get("content") or ""
        # If LLM returned empty/junk content after tools, use fallback
        stripped_reply = reply.strip()
        if tool_results and (not stripped_reply or stripped_reply in ("{}", "[]", "{{}}")):
            reply = self._fallback_reply(tool_results)

        # Post-process in background
        if reply:
            asyncio.create_task(self.post_process(
                message, reply, session_id,
                tool_calls=tool_results, new_turns=new_turns,
            ))

        return {
            "reply": reply,
            "tool_calls": tool_results,
            "route": "tool_calling",
        }

    # ------------------------------------------------------------------
    # Streaming chat
    # ------------------------------------------------------------------

    async def chat_stream(self, message: str, session_id: str = "default"):
        """Streaming tool-calling chat — yields NDJSON lines.

        Every LLM call is streaming. Text responses stream token-by-token.
        Tool calls are detected from the stream, executed, then the next
        LLM call streams the final response.
        """
        import time as _time

        t0 = _time.monotonic()

        # 1. Build system prompt
        memory_context = await self.memory.build_system_memory_context(session_id)
        active_project = await self.memory.get_active_project(session_id)
        system_prompt = build_tool_system_prompt(memory_context, active_project=active_project)

        # 2. Load conversation history
        history = await self.memory.get_working_memory(session_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        logger.info("[stream] setup done in %.1fms", (_time.monotonic() - t0) * 1000)

        # 3. Meta line
        yield json.dumps({"type": "meta", "route": "tool_calling"}) + "\n"

        # 4. Streaming tool-calling loop
        tool_results = []
        new_turns: list[dict] = []
        reply_text = ""

        for i in range(self.MAX_ITERATIONS):
            streamed_text = []
            tool_calls_found = None
            t_llm = _time.monotonic()
            # After tool execution, buffer response to detect junk (e.g. "{}")
            buffer_mode = bool(tool_results)

            try:
                first_token = True
                async for event in self.llm.stream_with_tool_detection(messages, tools=TOOLS):
                    if event["type"] == "token":
                        if first_token:
                            logger.info("[stream] iter %d: first token in %.1fms", i, (_time.monotonic() - t_llm) * 1000)
                            first_token = False
                        streamed_text.append(event["content"])
                        if not buffer_mode:
                            yield json.dumps({"type": "token", "content": event["content"]}) + "\n"
                    elif event["type"] == "tool_calls":
                        logger.info("[stream] iter %d: tool_calls detected in %.1fms — %s",
                                    i, (_time.monotonic() - t_llm) * 1000,
                                    [tc["function"]["name"] for tc in event["calls"]])
                        tool_calls_found = event["calls"]
            except Exception as e:
                logger.error("Stream failed (iteration %d): %s", i, e)
                fallback = self._fallback_reply(tool_results) if tool_results else "عذراً، حصل خطأ. حاول مرة ثانية."
                yield json.dumps({"type": "token", "content": fallback}) + "\n"
                reply_text = fallback
                break

            # Text was streamed directly — done
            if streamed_text:
                reply_text = "".join(streamed_text)
                # If post-tool response is junk, replace with fallback
                if buffer_mode and reply_text.strip() in ("{}", "[]", "{{}}"):
                    logger.warning("[stream] iter %d: junk response '%s', using fallback", i, reply_text.strip())
                    reply_text = self._fallback_reply(tool_results)
                    yield json.dumps({"type": "token", "content": reply_text}) + "\n"
                elif buffer_mode:
                    # Buffered text is valid — flush it now
                    yield json.dumps({"type": "token", "content": reply_text}) + "\n"
                logger.info("[stream] iter %d: text streamed, %d chars in %.1fms",
                            i, sum(len(c) for c in streamed_text), (_time.monotonic() - t_llm) * 1000)
                break

            if tool_calls_found:
                # Execute all tool calls in parallel
                parsed_calls = []
                for tc in tool_calls_found:
                    raw_args = tc["function"]["arguments"]
                    args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else (raw_args if isinstance(raw_args, dict) else {})
                    parsed_calls.append((tc, args))

                t_exec = _time.monotonic()
                results = await asyncio.gather(
                    *(self._execute_tool(tc["function"]["name"], args, session_id=session_id) for tc, args in parsed_calls),
                    return_exceptions=True,
                )
                logger.info("[stream] iter %d: tools executed in %.1fms", i, (_time.monotonic() - t_exec) * 1000)

                assistant_tc_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls_found,
                }
                messages.append(assistant_tc_msg)
                new_turns.append(assistant_tc_msg)

                for (tc, _), result in zip(parsed_calls, results):
                    if isinstance(result, Exception):
                        result = {"tool": tc["function"]["name"], "success": False, "error": str(result), "executed_at": _now()}
                    tool_results.append(result)
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                    messages.append(tool_msg)
                    new_turns.append(tool_msg)
                # Next iteration streams the response with tool results in context
                continue

            # Neither text nor tools — break
            break

        logger.info("[stream] total: %.1fms", (_time.monotonic() - t0) * 1000)

        # If loop ended without streaming any text, or streamed junk (e.g. "{}"), use fallback
        stripped_reply = reply_text.strip()
        if tool_results and (not stripped_reply or stripped_reply in ("{}", "[]", "{{}}")):
            reply_text = self._fallback_reply(tool_results)
            yield json.dumps({"type": "token", "content": reply_text}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

        # 5. Post-process in background
        if reply_text:
            asyncio.create_task(self.post_process(
                message, reply_text, session_id,
                tool_calls=tool_results, new_turns=new_turns,
            ))

    # ------------------------------------------------------------------
    # Post-processing (background)
    # ------------------------------------------------------------------

    # Tools that perform writes — auto-extraction is skipped when these were called
    _WRITE_TOOLS = {
        "create_reminder", "delete_reminder", "update_reminder",
        "add_expense", "record_debt", "pay_debt", "store_note",
        "manage_inventory", "manage_tasks", "manage_projects", "merge_projects",
        "manage_lists",
    }

    # Lightweight keyword check for storable content (Arabic + English)
    _STORABLE_RE = re.compile(
        r"(يعمل|يشتغل|يدرس|عمره|ساكن|متزوج|عنده|تخرج|يحب|"
        r"works at|lives in|married|born|age|graduated|likes|"
        r"شركة|جامعة|مدرسة|company|university|school)",
        re.IGNORECASE,
    )

    async def post_process(
        self, query_ar: str, reply_ar: str, session_id: str,
        tool_calls: list[dict] | None = None,
        new_turns: list[dict] | None = None,
    ) -> None:
        """Push to working memory + vector store + auto-extraction. Runs in background."""
        try:
            # Store full tool-calling conversation in working memory so the model
            # sees the correct pattern (user → tool_calls → tool results → reply)
            # This prevents hallucinated confirmations in subsequent turns.
            await self.memory.push_message(session_id, "user", query_ar)
            for turn in (new_turns or []):
                await self.memory.push_raw(session_id, turn)
            await self.memory.push_message(session_id, "assistant", reply_ar)

            # Store as vector embedding (Arabic — BGE-M3 handles multilingual)
            combined = f"User: {query_ar}\nAssistant: {reply_ar}"
            await self.vector.upsert_chunks(
                [combined],
                [{"source_type": "conversation", "topic": "chat"}],
            )

            # Auto-extraction: if no write tool was called, check for storable content
            tools_called = {tc.get("tool") for tc in (tool_calls or [])}
            if not (tools_called & self._WRITE_TOOLS) and self._STORABLE_RE.search(query_ar):
                await self._auto_extract(query_ar)

            # Periodic tasks
            msg_count = await self.memory.increment_message_count(session_id)

            if msg_count % settings.daily_summary_interval == 0:
                await self._trigger_daily_summary(session_id)

            if msg_count % settings.core_memory_interval == 0:
                await self._trigger_core_memory_extraction(session_id)

        except Exception as e:
            logger.error("Tool-calling post-processing failed: %s", e)

    # Entity types safe for auto-extraction from conversational messages.
    # Excludes Project, Task, Idea, Sprint, etc. which need explicit user intent.
    _AUTO_EXTRACT_SAFE_TYPES = {
        "Person", "Company", "Knowledge", "Location",
    }

    async def _auto_extract(self, query_ar: str) -> None:
        """Background extraction of storable facts from conversational messages."""
        try:
            ner_hints = ""
            if self.ner:
                entities = self.ner.extract_entities(query_ar)
                ner_hints = self.ner.format_hints(entities)

            query_en = await self.llm.translate_to_english(query_ar)
            facts = await self.llm.extract_facts_specialized(query_en, "general", ner_hints=ner_hints)

            if facts.get("entities"):
                # Filter out entity types that shouldn't be auto-created
                # from casual conversation (Projects, Tasks, Ideas, etc.)
                facts["entities"] = [
                    e for e in facts["entities"]
                    if e.get("entity_type") in self._AUTO_EXTRACT_SAFE_TYPES
                ]
                if not facts["entities"]:
                    return
                count = await self.graph.upsert_from_facts(facts)
                if count:
                    logger.info("Auto-extracted %d entities from conversational message", count)
        except Exception as e:
            logger.warning("Auto-extraction failed: %s", e)

    async def _trigger_daily_summary(self, session_id: str) -> None:
        try:
            messages = await self.memory.get_working_memory(session_id)
            if not messages:
                return
            text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in messages
            )
            summary = await self.llm.summarize_daily(text)
            await self.memory.set_daily_summary(summary)
        except Exception as e:
            logger.warning("Daily summary generation failed: %s", e)

    async def _trigger_core_memory_extraction(self, session_id: str) -> None:
        try:
            messages = await self.memory.get_working_memory(session_id)
            if not messages:
                return
            text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in messages
            )
            result = await self.llm.extract_core_preferences(text)
            for key, value in result.get("preferences", {}).items():
                if key and value:
                    await self.memory.set_core_memory(str(key), str(value))
        except Exception as e:
            logger.warning("Core memory extraction failed: %s", e)
