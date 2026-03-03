"""Home Assistant router — device states, service calls, names, webhook.

GET  /ha/states                       → all states (optional domain filter)
GET  /ha/states/{entity_id}           → single entity
POST /ha/services/{domain}/{service}  → call service
GET  /ha/names                        → custom Arabic name mappings
POST /ha/names                        → set mapping
DELETE /ha/names/{name}               → delete mapping
POST /ha/webhook                      → receive HA automation events → Telegram notify
"""

import logging

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/ha", tags=["homeassistant"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ServiceCallRequest(BaseModel):
    entity_id: str
    data: dict | None = None


class NameMappingRequest(BaseModel):
    entity_id: str
    arabic_name: str


class WebhookEvent(BaseModel):
    event_type: str = ""
    entity_id: str = ""
    new_state: str = ""
    old_state: str = ""
    message: str = ""


# ---------------------------------------------------------------------------
# State endpoints
# ---------------------------------------------------------------------------

@router.get("/states")
async def get_states(request: Request, domain: str | None = None):
    """Get all entity states, optionally filtered by domain."""
    ha = request.app.state.ha
    states = await ha.get_states(domain_filter=domain)
    # Return simplified view
    result = []
    for s in states:
        attrs = s.get("attributes", {})
        result.append({
            "entity_id": s.get("entity_id", ""),
            "state": s.get("state", ""),
            "friendly_name": attrs.get("friendly_name", ""),
            "domain": ha.get_domain(s.get("entity_id", "")),
            "attributes": attrs,
            "last_changed": s.get("last_changed", ""),
        })
    return {"states": result, "count": len(result)}


@router.get("/states/{entity_id:path}")
async def get_state(entity_id: str, request: Request):
    """Get a single entity state."""
    ha = request.app.state.ha
    state = await ha.get_state(entity_id)
    if not state:
        return {"error": f"Entity '{entity_id}' not found"}
    attrs = state.get("attributes", {})
    return {
        "entity_id": state.get("entity_id", ""),
        "state": state.get("state", ""),
        "friendly_name": attrs.get("friendly_name", ""),
        "attributes": attrs,
        "last_changed": state.get("last_changed", ""),
    }


# ---------------------------------------------------------------------------
# Service call
# ---------------------------------------------------------------------------

@router.post("/services/{domain}/{service}")
async def call_service(domain: str, service: str, body: ServiceCallRequest, request: Request):
    """Call an HA service (e.g., light/turn_on)."""
    ha = request.app.state.ha
    data = {"entity_id": body.entity_id}
    if body.data:
        data.update(body.data)
    result = await ha.call_service(domain, service, data)
    return result


# ---------------------------------------------------------------------------
# Custom Arabic names
# ---------------------------------------------------------------------------

@router.get("/names")
async def get_names(request: Request):
    """Get all custom Arabic name → entity_id mappings."""
    ha = request.app.state.ha
    names = await ha.get_entity_names()
    return {"names": names}


@router.post("/names")
async def set_name(body: NameMappingRequest, request: Request):
    """Set a custom Arabic name for an entity."""
    ha = request.app.state.ha
    await ha.set_entity_name(body.entity_id, body.arabic_name)
    return {"status": "ok", "arabic_name": body.arabic_name, "entity_id": body.entity_id}


@router.delete("/names/{name}")
async def delete_name(name: str, request: Request):
    """Delete a custom Arabic name mapping."""
    ha = request.app.state.ha
    await ha.delete_entity_name(name)
    return {"status": "deleted", "name": name}


# ---------------------------------------------------------------------------
# Webhook (HA → RAG)
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def ha_webhook(body: WebhookEvent, request: Request):
    """Receive HA automation events and send Telegram notification."""
    ha = request.app.state.ha

    # Resolve entity_id → friendly_name
    friendly_name = body.entity_id
    if body.entity_id:
        state = await ha.get_state(body.entity_id)
        if state:
            friendly_name = state.get("attributes", {}).get("friendly_name", body.entity_id)

    # Format message
    if body.message:
        text = f"🏠 {body.message}"
    else:
        event_label = body.event_type or "تحديث"
        state_label = body.new_state or "غير معروف"
        text = f"🏠 {event_label}: {friendly_name} → {state_label}"

    # Send Telegram notification
    tg_chat_id = _get_tg_chat_id(request)
    bot_token = _get_bot_token(request)
    if tg_chat_id and bot_token:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": tg_chat_id, "text": text},
                )
        except Exception as e:
            logger.error("HA webhook Telegram send failed: %s", e)

    return {"status": "ok", "message": text}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tg_chat_id(request: Request) -> str:
    user_ctx = getattr(request.state, "user_ctx", None)
    if user_ctx and user_ctx.tg_chat_id:
        return user_ctx.tg_chat_id
    return settings.tg_chat_id


def _get_bot_token(request: Request) -> str:
    user_ctx = getattr(request.state, "user_ctx", None)
    if user_ctx and getattr(user_ctx, "telegram_bot_token", ""):
        return user_ctx.telegram_bot_token
    return settings.telegram_bot_token
