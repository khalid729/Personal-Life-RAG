"""User management endpoints (admin-only)."""

import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


class RegisterUserRequest(BaseModel):
    user_id: str
    display_name: str = ""
    tg_chat_id: str = ""
    graph_name: str = ""
    collection_name: str = ""
    redis_prefix: str = ""


def _check_admin(request: Request) -> None:
    """Verify admin access via API key or localhost."""
    if not settings.admin_api_key:
        # If no admin key configured, allow only from localhost
        client = request.client
        if client and client.host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=403, detail="Admin access denied")
        return
    api_key = request.headers.get("X-Admin-Key", "")
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


@router.get("/users")
async def list_users(request: Request):
    _check_admin(request)
    registry = request.app.state.user_registry
    users = registry.list_users()
    return {
        "users": [
            {
                "user_id": u.user_id,
                "display_name": u.display_name,
                "graph_name": u.graph_name,
                "collection_name": u.collection_name,
                "tg_chat_id": u.tg_chat_id,
                "enabled": u.enabled,
            }
            for u in users
        ]
    }


@router.post("/users")
async def register_user(body: RegisterUserRequest, request: Request):
    _check_admin(request)
    registry = request.app.state.user_registry

    # Check if user already exists
    existing = registry.get_user_by_id(body.user_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"User '{body.user_id}' already exists")

    # Generate API key
    raw_api_key = secrets.token_urlsafe(32)

    profile = await registry.register_user(
        user_id=body.user_id,
        raw_api_key=raw_api_key,
        display_name=body.display_name,
        tg_chat_id=body.tg_chat_id,
        graph_name=body.graph_name,
        collection_name=body.collection_name,
        redis_prefix=body.redis_prefix,
    )

    # Create graph + collection for the new user
    graph = request.app.state.retrieval.graph
    vector = request.app.state.retrieval.vector
    await graph.ensure_user_graph(profile.graph_name)
    await vector.ensure_user_collection(profile.collection_name)

    return {
        "user_id": profile.user_id,
        "api_key": raw_api_key,
        "graph_name": profile.graph_name,
        "collection_name": profile.collection_name,
        "redis_prefix": profile.redis_prefix,
    }


@router.get("/users/by-telegram/{tg_id}")
async def get_user_by_telegram(tg_id: str, request: Request):
    _check_admin(request)
    registry = request.app.state.user_registry
    profile = registry.get_user_by_tg_id(tg_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No user with tg_chat_id={tg_id}")
    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "graph_name": profile.graph_name,
        "tg_chat_id": profile.tg_chat_id,
        "enabled": profile.enabled,
    }


@router.delete("/users/{user_id}")
async def disable_user(user_id: str, request: Request):
    _check_admin(request)
    registry = request.app.state.user_registry
    ok = await registry.disable_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return {"status": "disabled", "user_id": user_id}
