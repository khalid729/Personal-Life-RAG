import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.config import get_settings
from app.prompts.agentic import build_reflect, build_think
from app.prompts.classify import build_classify
from app.prompts.extract import build_context_enrichment, build_extract
from app.prompts.file_classify import build_file_classify
from app.prompts.conversation import CLARIFICATION_SYSTEM, CORE_MEMORY_SYSTEM
from app.prompts.translate import build_translate_ar_to_en, build_translate_en_to_ar
from app.prompts.vision import build_vision_analysis

logger = logging.getLogger(__name__)

settings = get_settings()


class LLMService:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def start(self):
        self._client = httpx.AsyncClient(
            base_url=settings.vllm_base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def stop(self):
        if self._client:
            await self._client.aclose()

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        body: dict = {
            "model": settings.vllm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        # Qwen3 needs enable_thinking: False; Qwen2.5 doesn't support it
        if "Qwen3" in settings.vllm_model:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        resp = await self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def translate_to_english(self, text: str) -> str:
        messages = build_translate_ar_to_en(text)
        return await self.chat(messages, max_tokens=1024, temperature=0.1)

    async def translate_to_arabic(self, text: str) -> str:
        messages = build_translate_en_to_ar(text)
        return await self.chat(messages, max_tokens=1024, temperature=0.1)

    async def extract_facts(self, text: str, ner_hints: str = "") -> dict:
        messages = build_extract(text, ner_hints=ner_hints)
        raw = await self.chat(messages, max_tokens=2048, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse extract_facts JSON: %s", raw[:200])
            return {"entities": []}

    async def classify_input(self, text: str) -> dict:
        messages = build_classify(text)
        raw = await self.chat(messages, max_tokens=128, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse classify JSON: %s", raw[:200])
            return {"category": "general", "confidence": 0.0}

    async def add_context_to_chunk(self, chunk: str, full_document: str) -> str:
        messages = build_context_enrichment(chunk, full_document)
        return await self.chat(messages, max_tokens=512, temperature=0.1)

    async def summarize_daily(self, messages_text: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Summarize the following conversation messages into a concise daily summary. "
                    "Focus on key facts, decisions, tasks, and important information. "
                    "Keep it under 500 words. Output only the summary."
                ),
            },
            {"role": "user", "content": messages_text},
        ]
        return await self.chat(messages, max_tokens=1024, temperature=0.3)

    async def classify_file(self, image_b64: str, mime_type: str) -> dict:
        messages = build_file_classify(image_b64, mime_type)
        raw = await self.chat(messages, max_tokens=256, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse classify_file JSON: %s", raw[:200])
            return {"file_type": "info_image", "confidence": 0.0, "brief_description": ""}

    async def analyze_image(
        self, image_b64: str, file_type: str, mime_type: str, user_context: str = ""
    ) -> dict:
        messages = build_vision_analysis(image_b64, file_type, mime_type, user_context)
        raw = await self.chat(messages, max_tokens=2048, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse analyze_image JSON: %s", raw[:200])
            return {"error": "Failed to parse analysis", "raw": raw[:500]}

    async def think_step(self, query_en: str) -> dict:
        messages = build_think(query_en)
        raw = await self.chat(messages, max_tokens=512, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse think_step JSON: %s", raw[:200])
            return {"strategy": "vector", "search_queries": [query_en], "reasoning": "fallback"}

    async def reflect_step(self, query_en: str, chunks: list[str]) -> dict:
        messages = build_reflect(query_en, chunks)
        raw = await self.chat(messages, max_tokens=1024, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse reflect_step JSON: %s", raw[:200])
            return {"sufficient": True, "chunk_scores": [], "retry_strategy": None}

    async def generate_response(
        self,
        query: str,
        context: str,
        memory_context: str,
        conversation_history: list[dict] | None = None,
    ) -> str:
        from datetime import datetime, timedelta, timezone
        from app.config import get_settings as _gs
        riyadh_tz = timezone(timedelta(hours=_gs().timezone_offset_hours))
        now = datetime.now(riyadh_tz)
        today_str = now.strftime("%Y-%m-%d")
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        weekdays_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        today_weekday = weekdays_ar[now.weekday()]
        tomorrow_weekday = weekdays_ar[(now.weekday() + 1) % 7]

        system_prompt = f"""أنت مساعد شخصي ذكي لإدارة الحياة اليومية. اسمك "المساعد".
ترد بالعربية السعودية العامية. كن مختصر ومفيد.

الوقت الحالي: {now.strftime("%H:%M")}
اليوم = {today_weekday} {today_str}
بكرة/غداً = {tomorrow_weekday} {tomorrow_str}
مهم: لما المستخدم يقول "بكرة" أو "غداً" يقصد {tomorrow_weekday} {tomorrow_str} وليس اليوم.

ذاكرتك:
{memory_context}

معلومات متاحة:
{context}

تعليمات:
- رد بالعربي السعودي العامي
- لو المعلومات موجودة في السياق، استخدمها
- لو ما عندك معلومات كافية، قول بصراحة
- كن مختصر وواضح
- لو المستخدم يشير لشي قاله قبل، ارجع لسياق المحادثة"""
        messages = [{"role": "system", "content": system_prompt}]

        # Inject conversation history as actual message turns
        if conversation_history:
            for turn in conversation_history:
                messages.append({
                    "role": turn["role"],
                    "content": turn["content"],
                })

        messages.append({"role": "user", "content": query})
        return await self.chat(messages, max_tokens=2048, temperature=0.7)

    async def check_clarification(self, query_en: str, action_type: str) -> dict:
        """Check if user message has enough info for the action."""
        messages = [
            {"role": "system", "content": CLARIFICATION_SYSTEM},
            {"role": "user", "content": f"Action type: {action_type}\nUser message: {query_en}"},
        ]
        raw = await self.chat(messages, max_tokens=256, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse clarification JSON: %s", raw[:200])
            return {"complete": True, "missing_fields": [], "clarification_question_ar": ""}

    async def extract_core_preferences(self, recent_messages: str) -> dict:
        """Extract user preferences from recent conversation."""
        messages = [
            {"role": "system", "content": CORE_MEMORY_SYSTEM},
            {"role": "user", "content": recent_messages},
        ]
        raw = await self.chat(messages, max_tokens=512, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse core_preferences JSON: %s", raw[:200])
            return {"preferences": {}}

    # --- Streaming (Phase 11) ---

    async def chat_stream(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        body = {
            "model": settings.vllm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if "Qwen3" in settings.vllm_model:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        async with self._client.stream("POST", "/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def generate_response_stream(
        self,
        query: str,
        context: str,
        memory_context: str,
        conversation_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        from datetime import datetime, timedelta, timezone
        from app.config import get_settings as _gs
        riyadh_tz = timezone(timedelta(hours=_gs().timezone_offset_hours))
        now = datetime.now(riyadh_tz)
        today_str = now.strftime("%Y-%m-%d")
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        weekdays_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
        today_weekday = weekdays_ar[now.weekday()]
        tomorrow_weekday = weekdays_ar[(now.weekday() + 1) % 7]

        system_prompt = f"""أنت مساعد شخصي ذكي لإدارة الحياة اليومية. اسمك "المساعد".
ترد بالعربية السعودية العامية. كن مختصر ومفيد.

الوقت الحالي: {now.strftime("%H:%M")}
اليوم = {today_weekday} {today_str}
بكرة/غداً = {tomorrow_weekday} {tomorrow_str}
مهم: لما المستخدم يقول "بكرة" أو "غداً" يقصد {tomorrow_weekday} {tomorrow_str} وليس اليوم.

ذاكرتك:
{memory_context}

معلومات متاحة:
{context}

تعليمات:
- رد بالعربي السعودي العامي
- لو المعلومات موجودة في السياق، استخدمها
- لو ما عندك معلومات كافية، قول بصراحة
- كن مختصر وواضح
- لو المستخدم يشير لشي قاله قبل، ارجع لسياق المحادثة"""
        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for turn in conversation_history:
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": query})

        async for chunk in self.chat_stream(messages, max_tokens=2048, temperature=0.7):
            yield chunk

    # --- Conversation Summarization (Phase 11) ---

    async def summarize_conversation(self, messages: list[dict]) -> str:
        formatted = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages
        )
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "لخص هذه المحادثة بشكل مختصر بالعربي. "
                    "ركز على الحقائق والقرارات والسياق المهم. "
                    "اكتب الملخص فقط بدون مقدمات."
                ),
            },
            {"role": "user", "content": formatted},
        ]
        return await self.chat(prompt_messages, max_tokens=500, temperature=0.3)
