"""Home Assistant service — device control, state queries, custom Arabic names.

Connects to HA via REST API. States cached in Redis (30s TTL).
Custom Arabic names stored per-user in Redis hash.
"""

import json
import logging

import httpx

from app.config import get_settings
from app.middleware.auth import _current_redis_prefix

logger = logging.getLogger(__name__)
settings = get_settings()


def _normalize_ar(text: str) -> str:
    """Normalize Arabic text for fuzzy matching.

    Treats ة=ه, أ=إ=آ=ا, ى=ي, removes tashkeel.
    """
    t = text.lower().strip()
    # Tashkeel removal (diacritics)
    for c in "\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652":
        t = t.replace(c, "")
    # Normalize alef variants
    for c in "أإآ":
        t = t.replace(c, "ا")
    # taa marbuta ↔ haa
    t = t.replace("ة", "ه")
    # alef maqsura → yaa
    t = t.replace("ى", "ي")
    return t

# Domain → HA service mapping for common actions
_DOMAIN_ACTIONS = {
    "light": ["turn_on", "turn_off", "toggle"],
    "switch": ["turn_on", "turn_off", "toggle"],
    "climate": ["turn_on", "turn_off", "set_temperature", "set_hvac_mode"],
    "cover": ["open_cover", "close_cover", "stop_cover", "toggle"],
    "media_player": ["turn_on", "turn_off", "media_play", "media_pause",
                     "media_stop", "media_next_track", "media_previous_track",
                     "volume_set", "volume_up", "volume_down"],
    "fan": ["turn_on", "turn_off", "toggle"],
    "lock": ["lock", "unlock"],
    "automation": ["turn_on", "turn_off", "trigger", "toggle"],
    "scene": ["turn_on"],
    "script": ["turn_on", "turn_off"],
}


class HomeAssistantService:
    """Async HA REST client with Redis caching and Arabic name resolution."""

    def __init__(self, redis):
        self._redis = redis
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if not settings.ha_enabled:
            logger.info("Home Assistant integration disabled")
            return
        self._client = httpx.AsyncClient(
            base_url=settings.ha_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.ha_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        # Verify connection
        try:
            resp = await self._client.get("/api/")
            resp.raise_for_status()
            logger.info("Home Assistant connected: %s", resp.json().get("message", "ok"))
        except Exception as e:
            logger.warning("Home Assistant connection failed: %s", e)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    async def get_states(self, domain_filter: str | None = None) -> list[dict]:
        """Get all entity states (cached in Redis for ha_cache_ttl seconds)."""
        cache_key = "ha:states"
        cached = await self._redis.get(cache_key)
        if cached:
            states = json.loads(cached)
        else:
            try:
                resp = await self._client.get("/api/states")
                resp.raise_for_status()
                states = resp.json()
                await self._redis.set(
                    cache_key, json.dumps(states, ensure_ascii=False),
                    ex=settings.ha_cache_ttl,
                )
            except Exception as e:
                logger.error("HA get_states failed: %s", e)
                return []

        if domain_filter:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain_filter}.")]

        return states

    async def get_state(self, entity_id: str) -> dict | None:
        """Get single entity state."""
        try:
            resp = await self._client.get(f"/api/states/{entity_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("HA get_state(%s) failed: %s", entity_id, e)
            return None

    async def call_service(self, domain: str, service: str, data: dict | None = None) -> dict:
        """Call an HA service (e.g., light/turn_on)."""
        try:
            resp = await self._client.post(
                f"/api/services/{domain}/{service}",
                json=data or {},
            )
            resp.raise_for_status()
            # Invalidate state cache
            await self._redis.delete("ha:states")
            result = resp.json()
            return {"success": True, "result": result if isinstance(result, list) else [result]}
        except Exception as e:
            logger.error("HA call_service(%s/%s) failed: %s", domain, service, e)
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Entity resolution: Arabic name → entity_id
    # ------------------------------------------------------------------

    async def resolve_entity(self, name: str) -> str | None:
        """Resolve an Arabic device name to an HA entity_id.

        Resolution order:
        1. Direct entity_id (e.g., "light.mb")
        2. Custom Arabic nickname from Redis
        3. Fuzzy match on HA friendly_name
        """
        if not name:
            return None

        # 1. Direct entity_id check
        if "." in name and not " " in name:
            state = await self.get_state(name)
            if state:
                return name

        # 2. Custom nickname lookup
        prefix = _current_redis_prefix.get()
        names_key = f"{prefix}ha:names"
        entity_id = await self._redis.hget(names_key, name)
        if entity_id:
            return entity_id

        # 3. Fuzzy match on friendly_name from cached states
        states = await self.get_states()
        name_norm = _normalize_ar(name)

        # Exact match first (normalized)
        for s in states:
            fn = _normalize_ar(s.get("attributes", {}).get("friendly_name") or "")
            if fn == name_norm:
                return s["entity_id"]

        # Strip common Arabic prefixes (ال, اللمبه, النور, جهاز, نور, لمبة)
        _STRIP_PREFIXES = ["اللمبه ", "اللمبة ", "النور ", "نور ", "لمبة ", "لمبه ", "جهاز ", "مفتاح "]
        stripped = name_norm
        for p in _STRIP_PREFIXES:
            p_norm = _normalize_ar(p)
            if stripped.startswith(p_norm):
                stripped = stripped[len(p_norm):]
                break

        # Substring match (both directions) + stripped query
        matches: list[tuple[int, dict]] = []  # (score, state)
        query_words = set(name_norm.split())

        for s in states:
            fn = _normalize_ar(s.get("attributes", {}).get("friendly_name") or "")
            eid = s.get("entity_id", "")
            if not fn:
                continue

            # Query in friendly_name (e.g., "المطبخ" in "نور المطبخ")
            if name_norm in fn:
                matches.append((3, s))
                continue

            # Friendly_name in query (e.g., "يمين" in "اللمبه يمين")
            if fn in name_norm:
                matches.append((2, s))
                continue

            # Stripped query matches
            if stripped and (stripped in fn or fn in stripped or stripped == fn):
                matches.append((2, s))
                continue

            # Word-level: any query word matches friendly_name exactly
            fn_words = set(fn.split())
            common = query_words & fn_words
            if common and any(len(w) > 1 for w in common):
                matches.append((1, s))
                continue

            # entity_id match
            if name_norm in eid.lower() or stripped in eid.lower():
                matches.append((1, s))

        if not matches:
            return None

        # Domain preference based on query keywords (all normalized)
        # Maps keyword → set of preferred domains (light/switch are interchangeable for lighting)
        _DOMAIN_HINTS: list[tuple[list[str], set[str]]] = [
            (["لمبه", "نور", "اضاءه"], {"light", "switch"}),
            (["مفتاح", "سويتش"], {"switch", "light"}),
            (["مكيف", "تكييف", "حراره"], {"climate"}),
            (["ستاره", "ستائر"], {"cover"}),
            (["سبيكر", "مكبر", "ميديا", "تلفزيون", "شاشه"], {"media_player"}),
        ]
        preferred_domains: set[str] = set()
        for keywords, domains in _DOMAIN_HINTS:
            if any(_normalize_ar(kw) in name_norm for kw in keywords):
                preferred_domains = domains
                break

        def _sort_key(m):
            score, state = m
            eid = state.get("entity_id", "")
            fn_len = len(state.get("attributes", {}).get("friendly_name", ""))
            # Bonus for matching preferred domain
            domain = eid.split(".")[0] if "." in eid else ""
            domain_bonus = 1 if preferred_domains and domain in preferred_domains else 0
            return (-score, -domain_bonus, fn_len)

        matches.sort(key=_sort_key)
        return matches[0][1]["entity_id"]

    # ------------------------------------------------------------------
    # Custom Arabic names (per-user via Redis)
    # ------------------------------------------------------------------

    async def set_entity_name(self, entity_id: str, arabic_name: str) -> None:
        """Set a custom Arabic nickname for an entity."""
        prefix = _current_redis_prefix.get()
        names_key = f"{prefix}ha:names"
        await self._redis.hset(names_key, arabic_name, entity_id)

    async def delete_entity_name(self, arabic_name: str) -> None:
        """Delete a custom Arabic nickname."""
        prefix = _current_redis_prefix.get()
        names_key = f"{prefix}ha:names"
        await self._redis.hdel(names_key, arabic_name)

    async def get_entity_names(self) -> dict[str, str]:
        """Get all custom Arabic name → entity_id mappings."""
        prefix = _current_redis_prefix.get()
        names_key = f"{prefix}ha:names"
        data = await self._redis.hgetall(names_key)
        return dict(data) if data else {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_domain(self, entity_id: str) -> str:
        """Extract domain from entity_id (e.g., 'light.mb' → 'light')."""
        return entity_id.split(".")[0] if "." in entity_id else ""

    def format_state_summary(self, state: dict) -> str:
        """Format a single entity state for display."""
        eid = state.get("entity_id", "")
        attrs = state.get("attributes", {})
        fn = attrs.get("friendly_name", eid)
        st = state.get("state", "unknown")

        parts = [f"{fn}: {st}"]

        # Domain-specific details
        domain = self.get_domain(eid)
        if domain == "climate":
            temp = attrs.get("temperature") or attrs.get("current_temperature")
            if temp:
                parts.append(f"الحرارة: {temp}°")
            hvac = attrs.get("hvac_mode")
            if hvac:
                parts.append(f"الوضع: {hvac}")
        elif domain == "media_player":
            title = attrs.get("media_title")
            if title:
                parts.append(f"يشغل: {title}")
        elif domain == "sensor":
            unit = attrs.get("unit_of_measurement", "")
            if unit:
                parts[0] = f"{fn}: {st} {unit}"

        return " | ".join(parts)
