"""OpenClaw report endpoint — receives structured reports and saves to graph + Telegram."""

import base64
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/openclaw", tags=["openclaw"])

_SEVERITY_ICONS = {
    "info": "📊",
    "warning": "⚠️",
    "critical": "🚨",
}

_TZ = timezone(timedelta(hours=settings.timezone_offset_hours))


class ReportRequest(BaseModel):
    source: str
    title: str
    summary: str
    details: str = ""
    severity: str = "info"
    metadata: dict | None = None


@router.post("/report")
async def openclaw_report(body: ReportRequest, request: Request):
    """Receive a structured report, save as Knowledge node, send Telegram."""
    icon = _SEVERITY_ICONS.get(body.severity, "📊")
    now = datetime.now(_TZ).isoformat()

    # --- Save to graph as Knowledge node ---
    graph = request.app.state.retrieval.graph
    content = body.summary
    if body.details:
        content += "\n\n" + body.details

    params = {
        "title": body.title,
        "content": content,
        "category": "water-report",
        "source": body.source,
        "severity": body.severity,
        "now": now,
    }
    # Add flat metadata fields (primitives only for FalkorDB)
    if body.metadata:
        for k, v in body.metadata.items():
            if k == "chart_base64":
                continue  # skip binary data in graph
            if isinstance(v, (str, int, float, bool)):
                params[k] = v

    extra_fields = ", ".join(
        f"{k}: ${k}" for k in params if k not in ("title", "content", "category", "source", "severity", "now")
    )
    if extra_fields:
        extra_fields = ", " + extra_fields

    cypher = (
        "CREATE (k:Knowledge {"
        "title: $title, content: $content, category: $category, "
        "source: $source, severity: $severity, created_at: $now"
        f"{extra_fields}"
        "})"
    )
    try:
        await graph.query(cypher, params)
        logger.info("Saved report to graph: %s", body.title)
    except Exception as e:
        logger.error("Failed to save report to graph: %s", e)

    # --- Send Telegram ---
    tg_chat_id = _get_tg_chat_id(request)
    bot_token = _get_bot_token(request)

    if tg_chat_id and bot_token:
        text = f"{icon} *{body.title}*\n\n{body.summary}"
        if body.details:
            text += f"\n\n{body.details}"

        chart_b64 = (body.metadata or {}).get("chart_base64")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if chart_b64:
                    # Send as photo with caption
                    photo_bytes = base64.b64decode(chart_b64)
                    files = {"photo": ("chart.png", photo_bytes, "image/png")}
                    data = {"chat_id": tg_chat_id, "caption": text, "parse_mode": "Markdown"}
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                        data=data,
                        files=files,
                    )
                else:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": tg_chat_id, "text": text, "parse_mode": "Markdown"},
                    )
            logger.info("Telegram notification sent for: %s", body.title)
        except Exception as e:
            logger.error("Telegram send failed: %s", e)

    return {"status": "ok", "title": body.title, "saved": True}


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
