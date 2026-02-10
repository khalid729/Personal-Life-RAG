import json
import logging
from datetime import date

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class MemoryService:
    """Redis 3-layer memory system.

    Layer 1 - Working Memory: last N messages (Redis List + LTRIM)
    Layer 2 - Daily Summary: compressed daily summary (TTL: 7 days)
    Layer 3 - Core Memory: preferences and patterns (permanent Hash)
    """

    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def start(self):
        self._redis = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
        )
        await self._redis.ping()
        logger.info("Redis memory connected on port %s", settings.redis_port)

    async def stop(self):
        if self._redis:
            await self._redis.aclose()

    # --- Layer 1: Working Memory ---

    def _working_key(self, session_id: str) -> str:
        return f"working_memory:{session_id}"

    async def push_message(self, session_id: str, role: str, content: str) -> None:
        key = self._working_key(session_id)
        msg = json.dumps({"role": role, "content": content})
        await self._redis.rpush(key, msg)
        await self._redis.ltrim(key, -settings.working_memory_size * 2, -1)
        # TTL 24 hours
        await self._redis.expire(key, 86400)

    async def get_working_memory(self, session_id: str) -> list[dict]:
        key = self._working_key(session_id)
        raw_messages = await self._redis.lrange(key, 0, -1)
        return [json.loads(m) for m in raw_messages]

    # --- Layer 2: Daily Summary ---

    def _daily_key(self, day: date | None = None) -> str:
        d = day or date.today()
        return f"daily_summary:{d.isoformat()}"

    async def set_daily_summary(self, summary: str, day: date | None = None) -> None:
        key = self._daily_key(day)
        await self._redis.set(key, summary)
        await self._redis.expire(key, settings.daily_summary_ttl_days * 86400)

    async def get_daily_summary(self, day: date | None = None) -> str | None:
        return await self._redis.get(self._daily_key(day))

    # --- Layer 3: Core Memory (permanent) ---

    CORE_KEY = "core_memory"

    async def set_core_memory(self, field: str, value: str) -> None:
        await self._redis.hset(self.CORE_KEY, field, value)

    async def get_core_memory(self, field: str) -> str | None:
        return await self._redis.hget(self.CORE_KEY, field)

    async def get_all_core_memory(self) -> dict[str, str]:
        return await self._redis.hgetall(self.CORE_KEY)

    # --- Pending Actions (Phase 4) ---

    def _pending_key(self, session_id: str) -> str:
        return f"pending_action:{session_id}"

    async def set_pending_action(self, session_id: str, action: dict) -> None:
        key = self._pending_key(session_id)
        await self._redis.set(key, json.dumps(action))
        await self._redis.expire(key, settings.confirmation_ttl_seconds)

    async def get_pending_action(self, session_id: str) -> dict | None:
        raw = await self._redis.get(self._pending_key(session_id))
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    async def clear_pending_action(self, session_id: str) -> None:
        await self._redis.delete(self._pending_key(session_id))

    # --- Message Counter (Phase 4) ---

    def _msg_count_key(self, session_id: str) -> str:
        return f"msg_count:{session_id}"

    async def increment_message_count(self, session_id: str) -> int:
        key = self._msg_count_key(session_id)
        count = await self._redis.incr(key)
        await self._redis.expire(key, 86400)
        return count

    # --- Build combined context ---

    async def build_memory_context(self, session_id: str) -> str:
        """Original full context builder (kept for backward compatibility)."""
        parts = []

        # Core memory (preferences/patterns)
        core = await self.get_all_core_memory()
        if core:
            parts.append("=== Core Memory (Preferences) ===")
            for k, v in core.items():
                parts.append(f"- {k}: {v}")

        # Daily summary
        summary = await self.get_daily_summary()
        if summary:
            parts.append("\n=== Today's Summary ===")
            parts.append(summary)

        # Working memory (recent messages)
        messages = await self.get_working_memory(session_id)
        if messages:
            parts.append("\n=== Recent Conversation ===")
            for msg in messages:
                role = "User" if msg["role"] == "user" else "Assistant"
                # Truncate long messages
                content = msg["content"][:300]
                parts.append(f"{role}: {content}")

        return "\n".join(parts)

    async def build_system_memory_context(self, session_id: str) -> str:
        """Core memory + daily summary only (for system prompt in multi-turn mode).
        Conversation history is passed as separate message turns."""
        parts = []

        core = await self.get_all_core_memory()
        if core:
            parts.append("=== Core Memory (Preferences) ===")
            for k, v in core.items():
                parts.append(f"- {k}: {v}")

        summary = await self.get_daily_summary()
        if summary:
            parts.append("\n=== Today's Summary ===")
            parts.append(summary)

        return "\n".join(parts)

    async def get_conversation_turns(self, session_id: str) -> list[dict]:
        """Returns working memory messages as structured turns for multi-turn prompting."""
        return await self.get_working_memory(session_id)
