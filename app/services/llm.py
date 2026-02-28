import json
import logging
from collections.abc import AsyncGenerator

import httpx

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None

from app.config import get_settings
from app.prompts.extract import build_context_enrichment, build_extract
from app.prompts.extract_specialized import build_specialized_extract
from app.prompts.file_classify import build_file_classify
from app.prompts.translate import build_translate_ar_to_en, build_translate_en_to_ar
from app.prompts.vision import build_vision_analysis

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

logger = logging.getLogger(__name__)

settings = get_settings()


class LLMService:
    def __init__(self):
        self._vllm_client: httpx.AsyncClient | None = None
        self._anthropic_client = None

    async def start(self):
        self._vllm_client = httpx.AsyncClient(
            base_url=settings.vllm_base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        if settings.use_claude_for_chat and settings.anthropic_api_key and AsyncAnthropic:
            self._anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            logger.info("Claude API enabled for chat (model: %s)", settings.anthropic_model)

    async def stop(self):
        if self._vllm_client:
            await self._vllm_client.aclose()
        if self._anthropic_client:
            await self._anthropic_client.close()

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

        resp = await self._vllm_client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def translate_to_english(self, text: str) -> str:
        messages = build_translate_ar_to_en(text)
        return await self.chat(messages, max_tokens=1024, temperature=0.1)

    async def translate_to_arabic(self, text: str) -> str:
        messages = build_translate_en_to_ar(text)
        return await self.chat(messages, max_tokens=1024, temperature=0.1)

    async def extract_facts(self, text: str, ner_hints: str = "", project_name: str | None = None) -> dict:
        messages = build_extract(text, ner_hints=ner_hints, project_name=project_name)
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

    # --- Anthropic format converters ---

    @staticmethod
    def _convert_messages_to_anthropic(messages: list[dict]) -> tuple[list[dict], list[dict]]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns (system_content_blocks, anthropic_messages).
        """
        system_content = []
        anthropic_messages = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                text = msg.get("content", "")
                if text:
                    system_content.append({
                        "type": "text",
                        "text": text,
                        "cache_control": {"type": "ephemeral"},
                    })
                continue

            if role == "assistant":
                content_blocks = []
                text = msg.get("content")
                if text:
                    content_blocks.append({"type": "text", "text": text})
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", "{}")
                    try:
                        input_data = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else {}
                    except json.JSONDecodeError:
                        input_data = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": input_data,
                    })
                if content_blocks:
                    anthropic_messages.append({"role": "assistant", "content": content_blocks})
                continue

            if role == "tool":
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }
                # Group consecutive tool results into a single user message
                if (
                    anthropic_messages
                    and anthropic_messages[-1]["role"] == "user"
                    and isinstance(anthropic_messages[-1]["content"], list)
                    and anthropic_messages[-1]["content"]
                    and anthropic_messages[-1]["content"][0].get("type") == "tool_result"
                ):
                    anthropic_messages[-1]["content"].append(tool_result)
                else:
                    anthropic_messages.append({"role": "user", "content": [tool_result]})
                continue

            if role == "user":
                anthropic_messages.append({"role": "user", "content": msg.get("content", "")})

        return system_content, anthropic_messages

    @staticmethod
    def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
        """Convert OpenAI-format tool definitions to Anthropic format."""
        result = []
        for tool in tools:
            fn = tool.get("function", {})
            result.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    @staticmethod
    def _convert_anthropic_response(response) -> dict:
        """Convert Anthropic response to OpenAI-format message dict."""
        msg: dict = {"role": "assistant", "content": None, "tool_calls": None}
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                })

        if text_parts:
            msg["content"] = "\n".join(text_parts)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg

    # --- Tool Calling: dual backend ---

    async def _chat_with_tools_vllm(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        body = {
            "model": settings.vllm_model,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if "Qwen3" in settings.vllm_model:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        resp = await self._vllm_client.post(
            "/chat/completions", json=body,
            timeout=httpx.Timeout(180.0, connect=10.0),
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]

        if not msg.get("tool_calls") and msg.get("content"):
            parsed = self._parse_tool_calls_from_text(msg["content"])
            if parsed:
                msg["tool_calls"] = parsed
                msg["content"] = None
        return msg

    async def _chat_with_tools_anthropic(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        system_content, anthropic_messages = self._convert_messages_to_anthropic(messages)
        anthropic_tools = self._convert_tools_to_anthropic(tools)

        response = await self._anthropic_client.messages.create(
            model=settings.anthropic_model,
            system=system_content,
            messages=anthropic_messages,
            tools=anthropic_tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        logger.debug(
            "Claude usage: input=%d output=%d cache_read=%d",
            response.usage.input_tokens,
            response.usage.output_tokens,
            getattr(response.usage, "cache_read_input_tokens", 0),
        )
        return self._convert_anthropic_response(response)

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict:
        """Chat completion with tool calling. Returns OpenAI-format message dict."""
        if self._anthropic_client:
            try:
                return await self._chat_with_tools_anthropic(messages, tools, max_tokens, temperature)
            except Exception as e:
                logger.error("Claude API failed, falling back to vLLM: %s", e)
        return await self._chat_with_tools_vllm(messages, tools, max_tokens, temperature)

    async def _stream_vllm(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator[dict, None]:
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

        tool_calls_acc: dict[int, dict] = {}
        text_buffer = ""
        mode = None  # None -> "text" | "tools" | "tools_in_text"

        async with self._vllm_client.stream(
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

                content = delta.get("content")
                if content is None:
                    continue
                if mode == "tools":
                    continue
                if mode is None:
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

    async def _stream_anthropic(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator[dict, None]:
        system_content, anthropic_messages = self._convert_messages_to_anthropic(messages)
        anthropic_tools = self._convert_tools_to_anthropic(tools)

        tool_calls_acc: dict[int, dict] = {}

        async with self._anthropic_client.messages.stream(
            model=settings.anthropic_model,
            system=system_content,
            messages=anthropic_messages,
            tools=anthropic_tools,
            max_tokens=max_tokens,
            temperature=temperature,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls_acc[event.index] = {
                            "id": event.content_block.id,
                            "type": "function",
                            "function": {
                                "name": event.content_block.name,
                                "arguments": "",
                            },
                        }
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield {"type": "token", "content": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        idx = event.index
                        if idx in tool_calls_acc:
                            tool_calls_acc[idx]["function"]["arguments"] += event.delta.partial_json

        if tool_calls_acc:
            calls = [tool_calls_acc[idx] for idx in sorted(tool_calls_acc)]
            yield {"type": "tool_calls", "calls": calls}

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
        if self._anthropic_client:
            started = False
            try:
                async for chunk in self._stream_anthropic(messages, tools, max_tokens, temperature):
                    started = True
                    yield chunk
                return
            except Exception as e:
                logger.error("Claude streaming failed, falling back to vLLM: %s", e)
                if started:
                    return
        async for chunk in self._stream_vllm(messages, tools, max_tokens, temperature):
            yield chunk

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
        async with self._vllm_client.stream("POST", "/chat/completions", json=body) as resp:
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
