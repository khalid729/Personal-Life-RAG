import json
import logging
from collections.abc import AsyncGenerator

import httpx

from app.config import get_settings
from app.prompts.agentic import build_think
from app.prompts.classify import build_classify
from app.prompts.extract import build_context_enrichment, build_extract
from app.prompts.extract_specialized import build_specialized_extract
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

    async def extract_facts_specialized(self, text: str, route: str, ner_hints: str = "", conversation_context: str = "") -> dict:
        """Extract facts using a domain-specialized prompt based on route."""
        messages = build_specialized_extract(text, route, ner_hints=ner_hints, conversation_context=conversation_context)
        raw = await self.chat(messages, max_tokens=2048, temperature=0.1, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse extract_facts_specialized JSON: %s", raw[:200])
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

    async def generate_response(
        self,
        query: str,
        context: str,
        memory_context: str,
        conversation_history: list[dict] | None = None,
        extraction_summary: str = "",
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

        action_block = ""
        if extraction_summary:
            has_success = any(not line.startswith("FAILED") for line in extraction_summary.split("\n") if line.strip())
            has_failure = "FAILED" in extraction_summary
            if has_success and has_failure:
                action_block = f"\nنتائج الإجراءات (بعضها نجح وبعضها فشل):\n{extraction_summary}\n"
            elif has_failure:
                action_block = f"\nإجراءات فشلت:\n{extraction_summary}\n"
            else:
                action_block = f"\nإجراءات تمت بنجاح:\n{extraction_summary}\n"

        system_prompt = f"""أنت مساعد شخصي ذكي. رد بالعربي السعودي العامي. كن مختصر.

الوقت: {now.strftime("%H:%M")} | اليوم: {today_weekday} {today_str} | بكرة: {tomorrow_weekday} {tomorrow_str}
{action_block}
ذاكرتك:
{memory_context}

معلومات متاحة:
{context}

تعليمات:
- ردك لازم يكون نص عربي طبيعي — ممنوع ترجع JSON أو كود أو بيانات منظمة
- لا تضيف أسئلة متابعة أو اقتراحات في نهاية ردك — رد على السؤال فقط وخلاص
- لو في إجراءات نجحت، أكد للمستخدم بشكل طبيعي
- لو في إجراءات فشلت (FAILED)، ممنوع تقول "تم" — قول للمستخدم إن الإجراء ما نجح ووضح السبب
- استخدم المعلومات المتاحة لو موجودة
- لو ما تعرف، قول ما عندي معلومات
- لا تخترع معلومات أو أسماء غير موجودة في السياق
- ممنوع تخترع مبالغ أو مصاريف أو أرقام مالية — اذكر فقط الأرقام الموجودة في المعلومات المتاحة
- لا تربط شخص بموضوع إلا إذا العلاقة مذكورة صريح في السياق"""
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

    # --- Tool Calling ---

    @staticmethod
    def _parse_tool_calls_from_text(content: str) -> list[dict] | None:
        """Fallback: extract tool calls from <tool_call> tags in text content.

        Some models (e.g. Qwen2.5-VL) output tool calls as text instead of
        structured tool_calls. This parses them into the OpenAI format.
        """
        import re
        import uuid
        # Match <tool_call>\n{...JSON...}\n</tool_call> or <tool_call>\n{...JSON...}\n⚗/📐/etc
        pattern = re.compile(
            r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>|[⚗📐\n])",
            re.DOTALL,
        )
        matches = pattern.findall(content)
        if not matches:
            return None
        tool_calls = []
        seen = set()
        for m in matches:
            try:
                parsed = json.loads(m)
                name = parsed.get("name", "")
                args = parsed.get("arguments", {})
                # Dedup — models sometimes repeat the same call
                dedup_key = f"{name}:{json.dumps(args, sort_keys=True)}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                })
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool call JSON: %s", m[:200])
                continue
        return tool_calls if tool_calls else None

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict:
        """Chat completion with tool calling. Returns raw message dict (may contain tool_calls)."""
        body = {
            "model": settings.vllm_model,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if "Qwen3" in settings.vllm_model:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        # Longer timeout for tool-calling (context grows with tool results)
        resp = await self._client.post(
            "/chat/completions", json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]

        # If vLLM didn't parse tool_calls but the text contains <tool_call> tags,
        # parse them ourselves (Qwen2.5-VL outputs tool calls as text).
        if not msg.get("tool_calls") and msg.get("content"):
            parsed = self._parse_tool_calls_from_text(msg["content"])
            if parsed:
                msg["tool_calls"] = parsed
                msg["content"] = None  # Clear text — it was a tool call, not a response

        return msg

    async def stream_with_tool_detection(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AsyncGenerator[dict, None]:
        """Stream response, auto-detecting tool calls vs text.

        Yields dicts:
        - {"type": "token", "content": "..."} for text chunks
        - {"type": "tool_calls", "calls": [...]} for collected tool calls (once, at end)
        """
        import uuid

        body = {
            "model": settings.vllm_model,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if "Qwen3" in settings.vllm_model:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        # Accumulators
        tool_calls_acc: dict[int, dict] = {}  # index -> {id, function{name, arguments}}
        text_buffer = ""
        mode = None  # None -> "text" | "tools" | "tools_in_text"

        async with self._client.stream(
            "POST", "/chat/completions", json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

                # --- Tool call deltas ---
                if "tool_calls" in delta and delta["tool_calls"]:
                    mode = "tools"
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                "type": "function",
                                "function": {
                                    "name": tc_delta.get("function", {}).get("name", ""),
                                    "arguments": "",
                                },
                            }
                        else:
                            if tc_delta.get("id"):
                                tool_calls_acc[idx]["id"] = tc_delta["id"]
                            if tc_delta.get("function", {}).get("name"):
                                tool_calls_acc[idx]["function"]["name"] = tc_delta["function"]["name"]
                        args_delta = tc_delta.get("function", {}).get("arguments", "")
                        if args_delta:
                            tool_calls_acc[idx]["function"]["arguments"] += args_delta
                    continue

                # --- Content deltas ---
                content = delta.get("content")
                if content is None:
                    continue

                if mode == "tools":
                    # Text after tool_calls — ignore
                    continue

                if mode is None:
                    # Accumulate initial buffer to detect <tool_call> tags
                    text_buffer += content
                    if len(text_buffer) > 30:
                        if "<tool_call>" in text_buffer:
                            mode = "tools_in_text"
                        else:
                            mode = "text"
                            yield {"type": "token", "content": text_buffer}
                            text_buffer = ""
                elif mode == "text":
                    yield {"type": "token", "content": content}
                elif mode == "tools_in_text":
                    text_buffer += content

        # --- End of stream ---
        if mode is None and text_buffer:
            if "<tool_call>" in text_buffer:
                mode = "tools_in_text"
            else:
                yield {"type": "token", "content": text_buffer}
                return

        if mode == "tools":
            calls = [tool_calls_acc[idx] for idx in sorted(tool_calls_acc)]
            yield {"type": "tool_calls", "calls": calls}
        elif mode == "tools_in_text":
            parsed = self._parse_tool_calls_from_text(text_buffer)
            if parsed:
                yield {"type": "tool_calls", "calls": parsed}
            else:
                yield {"type": "token", "content": text_buffer}

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
        extraction_summary: str = "",
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

        action_block = ""
        if extraction_summary:
            has_success = any(not line.startswith("FAILED") for line in extraction_summary.split("\n") if line.strip())
            has_failure = "FAILED" in extraction_summary
            if has_success and has_failure:
                action_block = f"\nنتائج الإجراءات (بعضها نجح وبعضها فشل):\n{extraction_summary}\n"
            elif has_failure:
                action_block = f"\nإجراءات فشلت:\n{extraction_summary}\n"
            else:
                action_block = f"\nإجراءات تمت بنجاح:\n{extraction_summary}\n"

        system_prompt = f"""أنت مساعد شخصي ذكي. رد بالعربي السعودي العامي. كن مختصر.

الوقت: {now.strftime("%H:%M")} | اليوم: {today_weekday} {today_str} | بكرة: {tomorrow_weekday} {tomorrow_str}
{action_block}
ذاكرتك:
{memory_context}

معلومات متاحة:
{context}

تعليمات:
- ردك لازم يكون نص عربي طبيعي — ممنوع ترجع JSON أو كود أو بيانات منظمة
- لا تضيف أسئلة متابعة أو اقتراحات في نهاية ردك — رد على السؤال فقط وخلاص
- لو في إجراءات نجحت، أكد للمستخدم بشكل طبيعي
- لو في إجراءات فشلت (FAILED)، ممنوع تقول "تم" — قول للمستخدم إن الإجراء ما نجح ووضح السبب
- استخدم المعلومات المتاحة لو موجودة
- لو ما تعرف، قول ما عندي معلومات
- لا تخترع معلومات أو أسماء غير موجودة في السياق
- ممنوع تخترع مبالغ أو مصاريف أو أرقام مالية — اذكر فقط الأرقام الموجودة في المعلومات المتاحة
- لا تربط شخص بموضوع إلا إذا العلاقة مذكورة صريح في السياق"""
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
