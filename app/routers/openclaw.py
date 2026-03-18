"""OpenClaw integration — receives structured reports, stores in graph + vector,
sends critical alerts immediately via Telegram.  Non-critical reports are
picked up by the morning summary job instead.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/integrations/openclaw", tags=["openclaw"])

_SEVERITY_ICONS = {
    "info": "📊",
    "warning": "⚠️",
    "critical": "🚨",
}

_TZ = timezone(timedelta(hours=settings.timezone_offset_hours))


class ReportRequest(BaseModel):
    source: str               # "homeassistant", "frigate", "network"
    title: str
    summary: str
    details: str = ""
    severity: str = "info"    # "info", "warning", "critical"
    timestamp: str = ""
    metadata: dict | None = None


@router.post("/report")
async def openclaw_report(body: ReportRequest, request: Request):
    """Receive a structured report, save as Knowledge node + embed, notify on critical."""
    now = datetime.now(_TZ).isoformat()
    report_time = body.timestamp or now

    graph = request.app.state.retrieval.graph
    retrieval = request.app.state.retrieval

    # --- Build content ---
    content = body.summary
    if body.details:
        content += "\n\n" + body.details

    # --- Save to graph as Knowledge node ---
    category = f"openclaw-{body.source}"
    params: dict = {
        "title": body.title,
        "content": content,
        "category": category,
        "source": "openclaw",
        "severity": body.severity,
        "report_time": report_time,
        "now": now,
    }
    # Add flat metadata fields (primitives only for FalkorDB)
    if body.metadata:
        for k, v in body.metadata.items():
            if k == "chart_base64":
                continue  # skip binary data
            if isinstance(v, (str, int, float, bool)):
                params[k] = v

    extra_fields = ", ".join(
        f"{k}: ${k}" for k in params
        if k not in ("title", "content", "category", "source", "severity", "report_time", "now")
    )
    if extra_fields:
        extra_fields = ", " + extra_fields

    cypher = (
        "CREATE (k:Knowledge {"
        "title: $title, content: $content, category: $category, "
        "source: $source, severity: $severity, report_time: $report_time, "
        "created_at: $now"
        f"{extra_fields}"
        "})"
    )
    try:
        await graph.query(cypher, params)
        logger.info("Saved OpenClaw report to graph: %s", body.title)
    except Exception as e:
        logger.error("Failed to save OpenClaw report to graph: %s", e)

    # --- Embed for semantic search (embed_only — already in graph) ---
    try:
        await retrieval.ingest_text(
            text=f"{body.title}\n{content}",
            source_type="openclaw_report",
            tags=[body.source, body.severity],
            embed_only=True,
        )
    except Exception as e:
        logger.error("Failed to embed OpenClaw report: %s", e)

    # --- Critical → immediate Telegram notification ---
    notified = False
    if body.severity == "critical":
        tg_chat_id = _get_tg_chat_id(request)
        bot_token = _get_bot_token(request)
        if tg_chat_id and bot_token:
            icon = _SEVERITY_ICONS.get(body.severity, "📊")
            text = f"{icon} *{body.title}*\n\n{body.summary}"
            if body.details:
                text += f"\n\n{body.details}"

            chart_b64 = (body.metadata or {}).get("chart_base64")
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    if chart_b64:
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
                notified = True
                logger.info("Critical alert sent via Telegram: %s", body.title)
            except Exception as e:
                logger.error("Telegram send failed: %s", e)

    return {"status": "ok", "title": body.title, "saved": True, "notified": notified}


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
