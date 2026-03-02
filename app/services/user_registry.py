"""User registry service for multi-tenancy.

Loads users from seed file, caches in memory, stores in Redis.
Provides fast API key → UserProfile lookup.
"""

import hashlib
import hmac
import json
import logging
from pathlib import Path

import redis.asyncio as aioredis

from app.config import get_settings
from app.models.schemas import UserProfile

logger = logging.getLogger(__name__)
settings = get_settings()


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class UserRegistry:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis
        self._by_key_hash: dict[str, UserProfile] = {}
        self._by_tg_id: dict[str, UserProfile] = {}
        self._by_user_id: dict[str, UserProfile] = {}

    async def start(self) -> None:
        """Load seed file, populate Redis + in-memory caches."""
        seed_path = Path(settings.users_file)
        if seed_path.exists():
            try:
                data = json.loads(seed_path.read_text(encoding="utf-8"))
                for user_id, info in data.items():
                    raw_key = info.pop("api_key", "")
                    key_hash = _hash_key(raw_key) if raw_key else ""
                    profile = UserProfile(
                        user_id=user_id,
                        api_key_hash=key_hash,
                        display_name=info.get("display_name", ""),
                        graph_name=info.get("graph_name", settings.falkordb_graph_name),
                        collection_name=info.get("collection_name", settings.qdrant_collection),
                        redis_prefix=info.get("redis_prefix", ""),
                        tg_chat_id=info.get("tg_chat_id", ""),
                        enabled=info.get("enabled", True),
                    )
                    await self._store_profile(profile, raw_key)
                logger.info("Loaded %d users from seed file", len(data))
            except Exception as e:
                logger.error("Failed to load seed file %s: %s", seed_path, e)
        else:
            logger.info("No seed file at %s — starting with empty registry", seed_path)

        # Also load from Redis (in case users were added via API)
        await self._load_from_redis()

    async def _store_profile(self, profile: UserProfile, raw_key: str = "") -> None:
        """Store profile in Redis + memory caches."""
        redis_key = f"rag:user:{profile.user_id}"
        await self._redis.hset(redis_key, mapping=profile.model_dump())
        # If we have raw key, store a reverse lookup
        if raw_key:
            await self._redis.set(f"rag:apikey:{profile.api_key_hash}", profile.user_id)
        self._cache_profile(profile)

    def _cache_profile(self, profile: UserProfile) -> None:
        """Update in-memory caches."""
        if profile.api_key_hash:
            self._by_key_hash[profile.api_key_hash] = profile
        if profile.tg_chat_id:
            self._by_tg_id[profile.tg_chat_id] = profile
        self._by_user_id[profile.user_id] = profile

    async def _load_from_redis(self) -> None:
        """Load all user profiles from Redis into memory cache."""
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor=cursor, match="rag:user:*", count=100)
            for key in keys:
                data = await self._redis.hgetall(key)
                if data:
                    profile = UserProfile(**data)
                    self._cache_profile(profile)
            if cursor == 0:
                break

    def get_user_by_api_key(self, raw_key: str) -> UserProfile | None:
        """Look up user by raw API key (constant-time comparison)."""
        key_hash = _hash_key(raw_key)
        for stored_hash, profile in self._by_key_hash.items():
            if hmac.compare_digest(stored_hash, key_hash) and profile.enabled:
                return profile
        return None

    def get_user_by_tg_id(self, tg_chat_id: str) -> UserProfile | None:
        """Reverse lookup: Telegram chat ID → UserProfile."""
        profile = self._by_tg_id.get(tg_chat_id)
        if profile and profile.enabled:
            return profile
        return None

    def get_user_by_id(self, user_id: str) -> UserProfile | None:
        """Lookup by user_id."""
        profile = self._by_user_id.get(user_id)
        if profile and profile.enabled:
            return profile
        return None

    def list_users(self) -> list[UserProfile]:
        """List all registered users."""
        return list(self._by_user_id.values())

    async def register_user(
        self, user_id: str, raw_api_key: str,
        display_name: str = "", tg_chat_id: str = "",
        graph_name: str = "", collection_name: str = "",
        redis_prefix: str = "",
    ) -> UserProfile:
        """Register a new user. Generates namespaced resource names if not provided."""
        if not graph_name:
            graph_name = f"personal_life_{user_id}"
        if not collection_name:
            collection_name = f"personal_life_{user_id}"
        if not redis_prefix:
            redis_prefix = f"{user_id}:"

        profile = UserProfile(
            user_id=user_id,
            api_key_hash=_hash_key(raw_api_key),
            display_name=display_name,
            graph_name=graph_name,
            collection_name=collection_name,
            redis_prefix=redis_prefix,
            tg_chat_id=tg_chat_id,
            enabled=True,
        )
        await self._store_profile(profile, raw_api_key)
        logger.info("Registered user: %s (graph=%s, collection=%s)",
                     user_id, graph_name, collection_name)
        return profile

    async def disable_user(self, user_id: str) -> bool:
        """Disable a user (soft delete)."""
        profile = self._by_user_id.get(user_id)
        if not profile:
            return False
        profile.enabled = False
        await self._store_profile(profile)
        return True
