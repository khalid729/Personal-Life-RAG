"""Auth middleware — resolves API key to UserContext and sets context vars.

When multi_tenant_enabled=False (default), all requests use the default
graph/collection/prefix from settings. Zero behavior change.
"""

import contextvars
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.models.schemas import UserContext

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Context variables — task-local, inherited by asyncio.create_task()
# ---------------------------------------------------------------------------

_current_graph_name: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_graph_name", default=None,
)
_current_collection: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_collection", default=None,
)
_current_redis_prefix: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_redis_prefix", default="",
)

# Paths that skip auth entirely
_SKIP_AUTH_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


def _default_user_context() -> UserContext:
    """Return context matching existing single-user settings."""
    return UserContext(
        user_id=settings.default_user_id,
        graph_name=settings.falkordb_graph_name,
        collection_name=settings.qdrant_collection,
        redis_prefix="",
        tg_chat_id=settings.tg_chat_id,
    )


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip auth for health/docs
        if path in _SKIP_AUTH_PATHS:
            return await call_next(request)

        ctx = self._resolve_user(request)
        request.state.user_ctx = ctx

        g_token = _current_graph_name.set(ctx.graph_name)
        c_token = _current_collection.set(ctx.collection_name)
        r_token = _current_redis_prefix.set(ctx.redis_prefix)
        try:
            return await call_next(request)
        finally:
            _current_graph_name.reset(g_token)
            _current_collection.reset(c_token)
            _current_redis_prefix.reset(r_token)

    def _resolve_user(self, request: Request) -> UserContext:
        """Resolve user from API key or return default."""
        if not settings.multi_tenant_enabled:
            return _default_user_context()

        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            return _default_user_context()

        registry = getattr(request.app.state, "user_registry", None)
        if not registry:
            return _default_user_context()

        profile = registry.get_user_by_api_key(api_key)
        if not profile:
            logger.warning("Invalid API key from %s", request.client.host if request.client else "?")
            return _default_user_context()

        return UserContext(
            user_id=profile.user_id,
            graph_name=profile.graph_name,
            collection_name=profile.collection_name,
            redis_prefix=profile.redis_prefix,
            tg_chat_id=profile.tg_chat_id,
        )
