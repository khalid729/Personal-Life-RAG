import json
import logging

import httpx

from app.config import get_settings
from app.prompts.agentic import build_reflect, build_think
from app.prompts.classify import build_classify
from app.prompts.extract import build_context_enrichment, build_extract
from app.prompts.file_classify import build_file_classify
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
        # Enable thinking for Qwen3
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

    async def extract_facts(self, text: str) -> dict:
        messages = build_extract(text)
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
        self, query: str, context: str, memory_context: str
    ) -> str:
        system_prompt = f"""أنت مساعد شخصي ذكي لإدارة الحياة اليومية. اسمك "المساعد".
ترد بالعربية السعودية العامية. كن مختصر ومفيد.

ذاكرتك:
{memory_context}

معلومات متاحة:
{context}

تعليمات:
- رد بالعربي السعودي العامي
- لو المعلومات موجودة في السياق، استخدمها
- لو ما عندك معلومات كافية، قول بصراحة
- كن مختصر وواضح"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]
        return await self.chat(messages, max_tokens=2048, temperature=0.7)
