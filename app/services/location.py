"""Location service — geofencing, zone tracking, reverse geocoding.

Provides haversine distance, geofence checks, and Nominatim reverse geocoding
with Redis caching. Used by the location router for location-triggered reminders.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# POI type map: Arabic label → OSM tag patterns
# ---------------------------------------------------------------------------

_POI_TYPE_MAP = {
    "بقالة": ["shop=supermarket", "shop=convenience"],
    "صيدلية": ["amenity=pharmacy"],
    "مطعم": ["amenity=restaurant", "amenity=fast_food"],
    "كافيه": ["amenity=cafe"],
    "مول": ["shop=mall", "shop=department_store"],
    "مسجد": ["amenity=place_of_worship"],
    "بنزينة": ["amenity=fuel"],
    "بنك": ["amenity=bank"],
    "مستشفى": ["amenity=hospital", "amenity=clinic"],
    "مدرسة": ["amenity=school"],
    "حديقة": ["leisure=park"],
    "مغسلة": ["shop=laundry"],
    "مكتبة": ["shop=books", "amenity=library"],
}

# Reverse map: "amenity=pharmacy" → "صيدلية"
_OSM_TAG_TO_AR: dict[str, str] = {}
for ar_name, tags in _POI_TYPE_MAP.items():
    for tag in tags:
        _OSM_TAG_TO_AR[tag] = ar_name


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two GPS coordinates."""
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_in_geofence(lat: float, lon: float, center_lat: float, center_lon: float, radius_m: float) -> bool:
    return haversine_distance(lat, lon, center_lat, center_lon) <= radius_m


# ---------------------------------------------------------------------------
# LocationService
# ---------------------------------------------------------------------------

class LocationService:
    def __init__(self, redis):
        self._redis = redis

    async def start(self) -> None:
        logger.info("Location service ready (enabled=%s)", settings.location_enabled)

    # --- Current position ---

    async def update_current_position(self, lat: float, lon: float) -> None:
        """Store current position + append to history."""
        tz = timezone(timedelta(hours=settings.timezone_offset_hours))
        now = datetime.now(tz).isoformat()
        await self._redis.hset("location:current", mapping={
            "lat": str(lat), "lon": str(lon), "updated_at": now,
        })
        await self._redis.lpush("location:history", f"{lat},{lon},{now}")
        await self._redis.ltrim("location:history", 0, 99)
        await self._redis.expire("location:history", 86400)

    async def get_current_position(self) -> dict | None:
        data = await self._redis.hgetall("location:current")
        if not data:
            return None
        return {
            "lat": float(data["lat"]),
            "lon": float(data["lon"]),
            "updated_at": data.get("updated_at", ""),
        }

    # --- Zone tracking ---

    async def get_current_zones(self) -> set[str]:
        members = await self._redis.smembers("location:current_zones")
        return set(members)

    async def enter_zone(self, name: str) -> None:
        await self._redis.sadd("location:current_zones", name)

    async def leave_zone(self, name: str) -> None:
        await self._redis.srem("location:current_zones", name)

    # --- Cooldown ---

    async def check_cooldown(self, zone_name: str) -> bool:
        """Return True if zone is still in cooldown."""
        return bool(await self._redis.exists(f"location:cooldown:{zone_name}"))

    async def set_cooldown(self, zone_name: str) -> None:
        ttl = settings.location_cooldown_minutes * 60
        await self._redis.set(f"location:cooldown:{zone_name}", "1", ex=ttl)

    # --- Geofence checking ---

    async def check_geofences(
        self, lat: float, lon: float, places: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """Check all places, return (entered, left) lists.

        Each item is a place dict with name, lat, lon, radius, etc.
        """
        current_zones = await self.get_current_zones()
        entered = []
        left = []
        now_inside: set[str] = set()

        for place in places:
            name = place.get("name", "")
            plat = float(place.get("lat", 0))
            plon = float(place.get("lon", 0))
            radius = float(place.get("radius", settings.location_default_radius))

            inside = is_in_geofence(lat, lon, plat, plon, radius)
            if inside:
                now_inside.add(name)
                if name not in current_zones:
                    entered.append(place)
                    await self.enter_zone(name)

        # Check for zones we left
        for zone_name in current_zones:
            if zone_name not in now_inside:
                # Find the place dict
                place_dict = next((p for p in places if p.get("name") == zone_name), {"name": zone_name})
                left.append(place_dict)
                await self.leave_zone(zone_name)

        return entered, left

    # --- Reverse geocoding (Nominatim) ---

    async def reverse_geocode(self, lat: float, lon: float) -> dict | None:
        """Reverse geocode via Nominatim with Redis cache (7-day TTL)."""
        cache_key = f"geocode:{lat:.4f}:{lon:.4f}"
        cached = await self._redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={
                        "lat": lat, "lon": lon,
                        "format": "json", "zoom": 18,
                        "accept-language": "ar",
                    },
                    headers={"User-Agent": settings.nominatim_user_agent},
                )
                resp.raise_for_status()
                data = resp.json()

            result = {
                "display_name": data.get("display_name", ""),
                "category": data.get("category", ""),
                "type": data.get("type", ""),
                "address": data.get("address", {}),
            }

            import json
            ttl = settings.nominatim_cache_ttl_days * 86400
            await self._redis.set(cache_key, json.dumps(result, ensure_ascii=False), ex=ttl)
            return result
        except Exception as e:
            logger.warning("Nominatim reverse geocode failed: %s", e)
            return None

    def classify_place_type(self, nominatim_result: dict | None) -> str | None:
        """Map Nominatim category+type to Arabic POI name."""
        if not nominatim_result:
            return None
        category = nominatim_result.get("category", "")
        ptype = nominatim_result.get("type", "")
        tag = f"{category}={ptype}"
        return _OSM_TAG_TO_AR.get(tag)
