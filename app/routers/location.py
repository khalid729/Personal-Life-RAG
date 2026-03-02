"""Location router — webhook for HA/OwnTracks + Place CRUD.

POST /location/update — main webhook (HA zone events + OwnTracks transitions)
GET  /location/places — list saved places
POST /location/places — create/update place
DELETE /location/places/{name} — delete place
GET  /location/current — current position
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/location", tags=["location"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LocationUpdateRequest(BaseModel):
    """Accepts both HA and OwnTracks payloads."""
    model_config = ConfigDict(populate_by_name=True)

    lat: float = 0.0
    lon: float = 0.0
    event: str = ""           # "enter" / "leave"
    zone_name: str = ""       # HA zone name
    source: str = ""          # "ha" / "owntracks"

    # OwnTracks fields
    type_field: str = Field("", alias="_type")  # "transition" / "location"
    desc: str = ""            # OwnTracks zone description
    tst: int = 0              # Unix timestamp


class PlaceRequest(BaseModel):
    name: str
    lat: float = 0.0
    lon: float = 0.0
    radius: float = 0.0
    place_type: str = ""
    address: str = ""


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@router.post("/update")
async def location_update(body: LocationUpdateRequest, request: Request):
    """Main webhook for HA and OwnTracks location updates."""
    if not settings.location_enabled:
        return {"status": "location_disabled"}

    graph = request.app.state.retrieval.graph
    location_svc = request.app.state.location

    # 1. Detect source + normalize
    lat, lon, event, zone_name = _normalize_payload(body)
    if lat == 0.0 and lon == 0.0:
        return {"status": "no_coordinates"}

    # 2. Update current position
    await location_svc.update_current_position(lat, lon)

    # 3. Get all saved places
    places = await graph.query_places()

    # 4. If HA zone_name provided and not in places, auto-create
    if zone_name and not any(p.get("name") == zone_name for p in places):
        await graph.create_place(
            name=zone_name, lat=lat, lon=lon,
            radius=settings.location_default_radius,
            source="ha_zone",
        )
        places.append({
            "name": zone_name, "lat": lat, "lon": lon,
            "radius": settings.location_default_radius,
        })
        logger.info("Auto-created HA zone as Place: %s", zone_name)

    # 5. Check geofences
    entered, left = await location_svc.check_geofences(lat, lon, places)

    # 6. Process entered zones — find matching reminders
    fired_reminders = []
    for place in entered:
        pname = place.get("name", "")
        if await location_svc.check_cooldown(pname):
            continue

        # Query reminders matching place NAME
        name_reminders = await graph.query_location_reminders(place_name=pname)
        fired_reminders.extend(name_reminders)

        # Reverse geocode → classify type → query reminders matching TYPE
        geo = await location_svc.reverse_geocode(lat, lon)
        ptype = location_svc.classify_place_type(geo)
        if ptype:
            type_reminders = await graph.query_location_reminders(place_type=ptype)
            # Dedup by title
            seen_titles = {r["title"] for r in fired_reminders}
            for r in type_reminders:
                if r["title"] not in seen_titles:
                    fired_reminders.append(r)
                    seen_titles.add(r["title"])

        await location_svc.set_cooldown(pname)

    # 7. Send Telegram notification for matched reminders
    notified_count = 0
    if fired_reminders:
        tg_chat_id = _get_tg_chat_id(request)
        if tg_chat_id:
            await _send_location_reminders(fired_reminders, entered, tg_chat_id)
            notified_count = len(fired_reminders)

        # 8. Mark notified
        for r in fired_reminders:
            try:
                await _mark_notified(r["title"], request)
            except Exception:
                pass

    # 9. Handle zone LEAVE — re-arm persistent location reminders
    for place in left:
        pname = place.get("name", "")
        await _rearm_persistent_location_reminders(pname, graph)

    return {
        "status": "ok",
        "position": {"lat": lat, "lon": lon},
        "entered": [p.get("name") for p in entered],
        "left": [p.get("name") for p in left],
        "reminders_fired": notified_count,
    }


# ---------------------------------------------------------------------------
# Place CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("/places")
async def list_places(request: Request, place_type: Optional[str] = None):
    graph = request.app.state.retrieval.graph
    places = await graph.query_places(place_type=place_type)
    return {"places": places}


@router.post("/places")
async def create_or_update_place(body: PlaceRequest, request: Request):
    graph = request.app.state.retrieval.graph
    await graph.create_place(
        name=body.name, lat=body.lat, lon=body.lon,
        radius=body.radius or settings.location_default_radius,
        place_type=body.place_type, source="user",
        address=body.address,
    )
    return {"status": "ok", "name": body.name}


@router.delete("/places/{name}")
async def delete_place(name: str, request: Request):
    graph = request.app.state.retrieval.graph
    await graph.delete_place(name)
    return {"status": "deleted", "name": name}


@router.get("/current")
async def current_position(request: Request):
    location_svc = request.app.state.location
    pos = await location_svc.get_current_position()
    zones = await location_svc.get_current_zones()
    return {"position": pos, "current_zones": list(zones)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_payload(body: LocationUpdateRequest) -> tuple[float, float, str, str]:
    """Normalize HA/OwnTracks payload → (lat, lon, event, zone_name)."""
    # OwnTracks transition
    if body.type_field == "transition":
        return body.lat, body.lon, body.event, body.desc

    # OwnTracks location update (no zone)
    if body.type_field == "location":
        return body.lat, body.lon, "", ""

    # HA webhook
    if body.source == "ha" or body.zone_name:
        return body.lat, body.lon, body.event, body.zone_name

    # Generic
    return body.lat, body.lon, body.event, body.zone_name


def _get_tg_chat_id(request: Request) -> str:
    """Get Telegram chat ID from user context or settings."""
    user_ctx = getattr(request.state, "user_ctx", None)
    if user_ctx and user_ctx.tg_chat_id:
        return user_ctx.tg_chat_id
    return settings.tg_chat_id


async def _send_location_reminders(
    reminders: list[dict], entered_places: list[dict], tg_chat_id: str,
) -> None:
    """Send Telegram notification for location-triggered reminders."""
    if not settings.telegram_bot_token or not tg_chat_id:
        return

    lines = ["📍 تذكيرات حسب الموقع:\n"]
    place_names = {p.get("name", "") for p in entered_places}

    for r in reminders:
        priority = r.get("priority") or 0
        icon = "🔴" if priority >= 4 else "📍"
        lines.append(f"{icon} {r['title']}")
        # Show which place triggered it
        if r.get("location_place") and r["location_place"] in place_names:
            lines.append(f"   أنت قريب من: {r['location_place']}")
        elif r.get("location_type"):
            nearby = ", ".join(p.get("name", "") for p in entered_places[:2])
            lines.append(f"   أنت قريب من: {nearby}")

    text = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": tg_chat_id, "text": text},
            )
    except Exception as e:
        logger.error("Failed to send location reminder via Telegram: %s", e)


async def _mark_notified(title: str, request: Request) -> None:
    """Call proactive mark-notified endpoint."""
    try:
        async with httpx.AsyncClient(
            base_url=f"http://localhost:{settings.api_port}", timeout=10,
        ) as client:
            # Forward the API key header if present
            headers = {}
            api_key = request.headers.get("X-API-Key", "")
            if api_key:
                headers["X-API-Key"] = api_key
            await client.post(
                "/proactive/mark-notified",
                json={"title": title},
                headers=headers,
            )
    except Exception as e:
        logger.debug("mark-notified failed for '%s': %s", title, e)


async def _rearm_persistent_location_reminders(place_name: str, graph) -> None:
    """On zone leave, clear notified_at on persistent location reminders so they re-fire."""
    try:
        q = """
        MATCH (r:Reminder)
        WHERE r.status = 'pending'
          AND r.persistent = true
          AND toLower(r.location_place) = toLower($place_name)
          AND r.notified_at IS NOT NULL
        SET r.notified_at = NULL
        RETURN count(r)
        """
        rows = await graph.query(q, {"place_name": place_name})
        count = rows[0][0] if rows else 0
        if count:
            logger.info("Re-armed %d persistent location reminder(s) for zone '%s'", count, place_name)
    except Exception as e:
        logger.debug("Failed to re-arm location reminders for '%s': %s", place_name, e)
