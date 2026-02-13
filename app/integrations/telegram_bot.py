"""
Telegram Bot for Personal Life RAG.

Standalone async process that calls the RAG API via httpx.
Uses aiogram 3.x with Dispatcher + Router.
Auth: only responds to configured TG_CHAT_ID.
"""

import asyncio
import io
import json
import logging
import sys
import time
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Add project root to path so we can import config
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

API_BASE = f"http://localhost:{settings.api_port}"
CHAT_TIMEOUT = 60.0
FILE_TIMEOUT = 120.0
TG_MAX_LEN = 4096

router = Router()

# Pending location updates for inventory items (module-level, single-process bot)
# {session_id: {"item_name": str, "created_at": float}}
_pending_locations: dict[str, dict] = {}
_PENDING_LOCATION_TTL = 300  # 5 minutes

# Active focus sessions for timer mode
# {chat_id: {"session_id": str, "task": str|None, "started_at": float, "duration": int}}
_active_focus_sessions: dict[str, dict] = {}

# Module-level scheduler reference (set during main())
_scheduler: AsyncIOScheduler | None = None


def _get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


# --- Helpers ---

def authorized(message: Message) -> bool:
    user_id = str(message.from_user.id)
    if user_id != settings.tg_chat_id:
        logger.warning("Unauthorized user: %s (expected %s)", user_id, settings.tg_chat_id)
        return False
    return True


def authorized_callback(callback: CallbackQuery) -> bool:
    return str(callback.from_user.id) == settings.tg_chat_id


def session_id(user_id: int) -> str:
    return f"tg_{user_id}"


# Arabic labels for analysis fields
_AR_LABELS = {
    # Common
    "description": "الوصف",
    "summary": "الملخص",
    "notes": "ملاحظات",
    "tags": "الوسوم",
    # Personal photo
    "people_count": "عدد الأشخاص",
    "location_hint": "المكان",
    "mood": "الأجواء",
    # Invoice
    "vendor": "المتجر/الجهة",
    "date": "التاريخ",
    "total_amount": "المبلغ الإجمالي",
    "currency": "العملة",
    "items": "العناصر",
    "payment_method": "طريقة الدفع",
    # Official document
    "document_type": "نوع المستند",
    "title": "العنوان",
    "parties": "الأطراف",
    "key_terms": "الشروط الرئيسية",
    "dates": "التواريخ",
    # Info image
    "extracted_text": "النص المستخرج",
    "content_type": "نوع المحتوى",
    "key_information": "المعلومات الرئيسية",
    # Note
    "content": "المحتوى",
    "note_type": "نوع الملاحظة",
    "language": "اللغة",
    "key_points": "النقاط الرئيسية",
    "action_items": "المطلوب تنفيذه",
    # Project file
    "file_description": "وصف الملف",
    "project_context": "سياق المشروع",
    "technologies": "التقنيات",
    "key_details": "تفاصيل مهمة",
    # Price list
    "validity": "الصلاحية",
    # Business card
    "name": "الاسم",
    "company": "الشركة",
    "phone": "الهاتف",
    "email": "الإيميل",
    "website": "الموقع",
    "address": "العنوان",
    "other": "أخرى",
    # Inventory item
    "item_name": "اسم الغرض",
    "quantity_visible": "الكمية المرئية",
    "condition": "الحالة",
    "brand": "الماركة",
    "model": "الموديل",
    "specifications": "المواصفات",
    "estimated_value": "القيمة التقديرية",
}

_AR_FILE_TYPES = {
    "invoice": "فاتورة",
    "official_document": "مستند رسمي",
    "personal_photo": "صورة شخصية",
    "info_image": "صورة معلومات",
    "note": "ملاحظة",
    "project_file": "ملف مشروع",
    "price_list": "قائمة أسعار",
    "business_card": "كرت شخصي",
    "inventory_item": "غرض/منتج",
}

_AR_STEPS = {
    "base64_encoded": "ترميز الصورة",
    "analyzed": "تحليل بالذكاء الاصطناعي",
    "graph_node_created": "حفظ في قاعدة العلاقات",
}


def split_message(text: str) -> list[str]:
    """Split text into chunks that fit Telegram's 4096 char limit."""
    if len(text) <= TG_MAX_LEN:
        return [text]

    parts = []
    while text:
        if len(text) <= TG_MAX_LEN:
            parts.append(text)
            break
        # Find a good split point (newline or space)
        split_at = text.rfind("\n", 0, TG_MAX_LEN)
        if split_at == -1 or split_at < TG_MAX_LEN // 2:
            split_at = text.rfind(" ", 0, TG_MAX_LEN)
        if split_at == -1:
            split_at = TG_MAX_LEN
        parts.append(text[:split_at])
        text = text[split_at:].lstrip()
    return parts


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ نعم", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ لا", callback_data="confirm_no"),
        ]
    ])


async def send_reply(message: Message, text: str, keyboard=None):
    """Send a reply, splitting if too long."""
    parts = split_message(text)
    for i, part in enumerate(parts):
        kb = keyboard if i == len(parts) - 1 else None
        await message.answer(part, reply_markup=kb)


async def api_get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=CHAT_TIMEOUT) as client:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, json: dict | None = None, timeout: float = CHAT_TIMEOUT) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=timeout) as client:
        resp = await client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()


async def api_put(path: str, json: dict | None = None) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=CHAT_TIMEOUT) as client:
        resp = await client.put(path, json=json)
        resp.raise_for_status()
        return resp.json()


async def api_post_file(
    path: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    data: dict | None = None,
) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=FILE_TIMEOUT) as client:
        files = {"file": (filename, file_bytes, content_type)}
        resp = await client.post(path, files=files, data=data or {})
        resp.raise_for_status()
        return resp.json()


async def chat_api(text: str, sid: str) -> dict:
    return await api_post("/chat/", json={"message": text, "session_id": sid})


async def chat_api_stream(text: str, sid: str, message: Message) -> dict:
    """Stream chat response — edit Telegram message as tokens arrive.

    Returns dict with 'text' (full response) and 'pending_confirmation' (bool).
    """
    full_text = ""
    last_edit = 0.0
    meta = {}

    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=120.0) as client:
            async with client.stream(
                "POST", "/chat/stream",
                json={"message": text, "session_id": sid},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg_type = data.get("type")
                    if msg_type == "meta":
                        meta = data
                    elif msg_type == "token":
                        full_text += data.get("content", "")
                        now = time.monotonic()
                        # Edit message every ~1 second to avoid rate limits
                        if now - last_edit >= 1.0 and full_text.strip():
                            try:
                                display = full_text
                                if len(display) > TG_MAX_LEN - 3:
                                    display = display[:TG_MAX_LEN - 3] + "..."
                                await message.edit_text(display)
                                last_edit = now
                            except Exception:
                                pass
                    elif msg_type == "done":
                        break
    except Exception as e:
        logger.error("Streaming chat failed: %s", e)
        if not full_text:
            # Fallback to non-streaming
            result = await chat_api(text, sid)
            return {
                "text": result.get("reply", "خطأ"),
                "pending_confirmation": result.get("pending_confirmation", False),
            }

    # Final edit with full text
    if full_text.strip():
        try:
            for part in split_message(full_text):
                await message.edit_text(part)
        except Exception:
            pass

    return {
        "text": full_text,
        "pending_confirmation": meta.get("pending_confirmation", False),
    }


# --- Commands ---

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not authorized(message):
        return
    await message.answer(
        "مرحباً! أنا مساعدك الشخصي 🤖\n\n"
        "أرسل لي نص، صوت، صورة، أو ملف وأنا أساعدك.\n\n"
        "الأوامر:\n"
        "/plan — خطة اليوم\n"
        "/debts — ملخص الديون\n"
        "/reminders — التذكيرات\n"
        "/projects — المشاريع\n"
        "/tasks — المهام\n"
        "/report — التقرير المالي\n"
        "/inventory — المخزون والأغراض\n"
        "/focus — جلسة تركيز (بومودورو)\n"
        "/sprint — السبرنتات\n"
        "/backup — نسخة احتياطية\n"
        "/graph — عرض الرسم البياني"
    )


@router.message(Command("plan"))
async def cmd_plan(message: Message):
    if not authorized(message):
        return
    result = await chat_api("رتب لي يومي", session_id(message.from_user.id))
    await send_reply(message, result["reply"])


@router.message(Command("debts"))
async def cmd_debts(message: Message):
    if not authorized(message):
        return
    data = await api_get("/financial/debts")
    lines = [
        f"💰 ملخص الديون",
        f"عليك: {data['total_i_owe']} ريال",
        f"لك: {data['total_owed_to_me']} ريال",
        f"الصافي: {data['net_position']} ريال",
        "",
    ]
    for d in data.get("debts", []):
        direction = "عليك" if d.get("direction") == "i_owe" else "لك"
        status = d.get("status", "open")
        lines.append(f"• {d['person']}: {d['amount']} ريال ({direction}) [{status}]")
    if not data.get("debts"):
        lines.append("لا توجد ديون حالياً.")
    await send_reply(message, "\n".join(lines))


@router.message(Command("reminders"))
async def cmd_reminders(message: Message):
    if not authorized(message):
        return
    data = await api_get("/reminders/")
    text = data.get("reminders", "لا توجد تذكيرات.")
    await send_reply(message, f"⏰ التذكيرات\n\n{text}")


@router.message(Command("projects"))
async def cmd_projects(message: Message):
    if not authorized(message):
        return
    data = await api_get("/projects/")
    text = data.get("projects", "لا توجد مشاريع.")
    await send_reply(message, f"📋 المشاريع\n\n{text}")


@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    if not authorized(message):
        return
    data = await api_get("/tasks/")
    text = data.get("tasks", "لا توجد مهام.")
    await send_reply(message, f"✅ المهام\n\n{text}")


@router.message(Command("report"))
async def cmd_report(message: Message):
    if not authorized(message):
        return
    data = await api_get("/financial/report")
    lines = [
        f"📊 التقرير المالي — {data['month']}/{data['year']}",
        f"الإجمالي: {data['total']} {data['currency']}",
        "",
    ]
    for cat in data.get("by_category", []):
        lines.append(f"• {cat['category']}: {cat['total']} ({cat['percentage']}%)")
    if not data.get("by_category"):
        lines.append("لا توجد مصاريف هذا الشهر.")
    await send_reply(message, "\n".join(lines))


def _format_inventory_report_ar(data: dict) -> str:
    lines = ["📊 تقرير المخزون\n"]
    lines.append(f"الإجمالي: {data['total_items']} غرض ({data['total_quantity']} وحدة)")
    if data.get("by_category"):
        lines.append("\n📂 حسب الفئة:")
        for c in data["by_category"]:
            lines.append(f"  • {c['category']}: {c['items']} أغراض ({c['quantity']} وحدة)")
    if data.get("by_location"):
        lines.append("\n📍 حسب المكان:")
        for loc in data["by_location"]:
            lines.append(f"  • {loc['location']}: {loc['items']} أغراض")
    if data.get("by_condition"):
        lines.append("\n🔧 حسب الحالة:")
        for c in data["by_condition"]:
            lines.append(f"  • {c['condition']}: {c['count']}")
    lines.append(f"\n⚠️ بدون مكان: {data.get('without_location', 0)}")
    lines.append(f"💤 مهملة: {data.get('unused_count', 0)}")
    if data.get("top_by_quantity"):
        lines.append("\n🏆 أكثر كمية:")
        for t in data["top_by_quantity"][:5]:
            lines.append(f"  • {t['name']}: {t['quantity']}")
    return "\n".join(lines)


@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    if not authorized(message):
        return
    # Check for "report" subcommand
    args = message.text.strip().split(maxsplit=1)
    if len(args) > 1 and args[1].strip().lower() == "report":
        data = await api_get("/inventory/report")
        text = _format_inventory_report_ar(data)
        await send_reply(message, text)
        return
    data = await api_get("/inventory/summary")
    total_items = data.get("total_items", 0)
    total_qty = data.get("total_quantity", 0)
    lines = [
        f"📦 المخزون",
        f"إجمالي الأغراض: {total_items} (الكمية: {total_qty})",
        "",
    ]
    by_cat = data.get("by_category", [])
    if by_cat:
        lines.append("حسب الفئة:")
        for c in by_cat:
            lines.append(f"  • {c['category']}: {c['count']} أغراض ({c['quantity']} حبة)")
    by_loc = data.get("by_location", [])
    if by_loc:
        lines.append("\nحسب المكان:")
        for loc in by_loc:
            lines.append(f"  • {loc['location']}: {loc['count']} أغراض")
    if not by_cat and not by_loc:
        lines.append("لا توجد أغراض مسجلة.")
    await send_reply(message, "\n".join(lines))


@router.message(Command("focus"))
async def cmd_focus(message: Message):
    if not authorized(message):
        return
    args = message.text.strip().split(maxsplit=2)
    chat_id = str(message.from_user.id)

    # /focus done — complete active session
    if len(args) > 1 and args[1].strip().lower() == "done":
        if chat_id in _active_focus_sessions:
            _active_focus_sessions.pop(chat_id)
        try:
            result = await api_post("/productivity/focus/complete", json={"completed": True})
            if "error" in result:
                await message.answer("ما في جلسة تركيز نشطة.")
            else:
                dur = result.get("duration_minutes", 0)
                await message.answer(f"تم إنهاء جلسة التركيز ({dur} دقيقة).")
        except Exception as e:
            logger.error("Focus complete failed: %s", e)
            await message.answer("خطأ في إنهاء الجلسة.")
        return

    # /focus stats — show statistics
    if len(args) > 1 and args[1].strip().lower() == "stats":
        try:
            data = await api_get("/productivity/focus/stats")
            lines = [
                "إحصائيات التركيز:",
                f"  اليوم: {data['today_sessions']} جلسات ({data['today_minutes']} دقيقة)",
                f"  الأسبوع: {data['week_sessions']} جلسات ({data['week_minutes']} دقيقة)",
                f"  الإجمالي: {data['total_sessions']} جلسات ({data['total_minutes']} دقيقة)",
            ]
            by_task = data.get("by_task", [])
            if by_task:
                lines.append("\nحسب المهمة:")
                for t in by_task[:5]:
                    lines.append(f"  • {t['task']}: {t['sessions']} ({t['minutes']} دقيقة)")
            await send_reply(message, "\n".join(lines))
        except Exception as e:
            logger.error("Focus stats failed: %s", e)
            await message.answer("خطأ في جلب الإحصائيات.")
        return

    # /focus [minutes] [task] — start session
    duration = settings.pomodoro_default_minutes
    task_name = None
    if len(args) > 1:
        try:
            duration = int(args[1])
        except ValueError:
            task_name = " ".join(args[1:])
    if len(args) > 2 and task_name is None:
        task_name = args[2]

    try:
        payload = {"duration_minutes": duration}
        if task_name:
            payload["task"] = task_name
        result = await api_post("/productivity/focus/start", json=payload)
        sid = result.get("session_id", "")

        # Store active session
        _active_focus_sessions[chat_id] = {
            "session_id": sid,
            "task": task_name,
            "started_at": time.monotonic(),
            "duration": duration,
        }

        task_line = f" على: {task_name}" if task_name else ""
        await message.answer(f"بدأت جلسة تركيز ({duration} دقيقة){task_line}\n/focus done لإنهاء الجلسة")

        # Schedule timer notification
        scheduler = _get_scheduler()
        if scheduler:
            from datetime import datetime as dt_cls, timedelta as td_cls
            run_at = dt_cls.utcnow() + td_cls(minutes=duration)
            bot = message.bot

            async def _focus_timer_callback(bot_ref=bot, cid=settings.tg_chat_id, s_id=sid):
                try:
                    await bot_ref.send_message(chat_id=cid, text=f"انتهى وقت جلسة التركيز! ({duration} دقيقة)\n/focus done لتسجيل الإنجاز")
                except Exception as e:
                    logger.error("Focus timer callback failed: %s", e)

            scheduler.add_job(
                _focus_timer_callback, "date", run_date=run_at,
                id=f"focus_timer_{sid}", replace_existing=True,
            )
    except Exception as e:
        logger.error("Focus start failed: %s", e)
        await message.answer("خطأ في بدء جلسة التركيز.")


@router.message(Command("backup"))
async def cmd_backup(message: Message):
    if not authorized(message):
        return
    args = message.text.strip().split(maxsplit=1)

    # /backup list
    if len(args) > 1 and args[1].strip().lower() == "list":
        try:
            data = await api_get("/backup/list")
            backups = data.get("backups", [])
            if not backups:
                await message.answer("لا توجد نسخ احتياطية.")
                return
            lines = ["النسخ الاحتياطية:"]
            for b in backups[:10]:
                size_mb = b["size_bytes"] / (1024 * 1024)
                lines.append(f"  {b['timestamp']} ({size_mb:.1f} MB)")
            await send_reply(message, "\n".join(lines))
        except Exception as e:
            logger.error("Backup list failed: %s", e)
            await message.answer("خطأ في جلب قائمة النسخ.")
        return

    # /backup — create backup
    await message.answer("جاري إنشاء نسخة احتياطية...")
    try:
        data = await api_post("/backup/create", timeout=300.0)
        sizes = data.get("sizes", {})
        lines = [
            f"تم إنشاء النسخة: {data.get('timestamp', '')}",
            f"  الرسم البياني: {sizes.get('graph', 0) / 1024:.0f} KB",
            f"  المتجهات: {sizes.get('vector', 0) / 1024:.0f} KB",
            f"  الذاكرة: {sizes.get('redis', 0) / 1024:.0f} KB",
        ]
        removed = data.get("old_backups_removed", 0)
        if removed:
            lines.append(f"  حذف {removed} نسخ قديمة")
        await send_reply(message, "\n".join(lines))
    except Exception as e:
        logger.error("Backup create failed: %s", e)
        await message.answer("خطأ في إنشاء النسخة الاحتياطية.")


@router.message(Command("graph"))
async def cmd_graph(message: Message):
    if not authorized(message):
        return
    args = message.text.strip().split(maxsplit=2)

    # /graph — schema overview
    if len(args) == 1:
        try:
            data = await api_get("/graph/schema")
            lines = [
                f"إحصائيات الرسم البياني:",
                f"  العقد: {data.get('total_nodes', 0)}",
                f"  العلاقات: {data.get('total_edges', 0)}",
                "",
                "أنواع العقد:",
            ]
            for label, count in sorted(data.get("node_labels", {}).items(), key=lambda x: -x[1]):
                lines.append(f"  {label}: {count}")
            rel_types = data.get("relationship_types", {})
            if rel_types:
                lines.append("\nأنواع العلاقات:")
                for rt, count in sorted(rel_types.items(), key=lambda x: -x[1])[:10]:
                    lines.append(f"  {rt}: {count}")
            await send_reply(message, "\n".join(lines))
        except Exception as e:
            logger.error("Graph schema failed: %s", e)
            await message.answer("خطأ في جلب معلومات الرسم البياني.")
        return

    # /graph Person — type subgraph as image
    # /graph محمد 2 — ego-graph
    entity_or_center = args[1].strip()
    hops = 2
    if len(args) > 2:
        try:
            hops = int(args[2].strip())
        except ValueError:
            pass

    await message.answer("جاري إنشاء صورة الرسم البياني...")
    try:
        # Check if it's a known entity type (capitalized English) or a center name
        _KNOWN_TYPES = {"Person", "Project", "Task", "Expense", "Debt", "Reminder",
                        "Company", "Item", "Knowledge", "Topic", "Tag", "Sprint", "Idea"}
        payload = {"width": 1200, "height": 800, "limit": 300}
        if entity_or_center in _KNOWN_TYPES:
            payload["entity_type"] = entity_or_center
        else:
            payload["center"] = entity_or_center
            payload["hops"] = hops

        async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
            resp = await client.post("/graph/image", json=payload)
            resp.raise_for_status()
            png_bytes = resp.content

        photo = BufferedInputFile(png_bytes, filename="graph.png")
        await message.answer_photo(photo=photo)
    except Exception as e:
        logger.error("Graph image failed: %s", e)
        await message.answer("خطأ في إنشاء صورة الرسم البياني.")


@router.message(Command("sprint"))
async def cmd_sprint(message: Message):
    if not authorized(message):
        return
    try:
        data = await api_get("/productivity/sprints/")
        sprints = data.get("sprints", [])
        if not sprints:
            await message.answer("لا توجد سبرنتات.")
            return
        lines = ["السبرنتات:"]
        for s in sprints:
            total = s.get("total_tasks", 0)
            done = s.get("done_tasks", 0)
            pct = s.get("progress_pct", 0)
            bar_filled = int(pct / 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            lines.append(
                f"\n{s['name']} [{s['status']}]"
                f"\n  {bar} {pct}% ({done}/{total})"
                f"\n  {s.get('start_date', '?')} → {s.get('end_date', '?')}"
            )
            if s.get("goal"):
                lines.append(f"  الهدف: {s['goal']}")
        await send_reply(message, "\n".join(lines))
    except Exception as e:
        logger.error("Sprint command failed: %s", e)
        await message.answer("خطأ في جلب السبرنتات.")


# --- Callback: Confirmation buttons ---

@router.callback_query(F.data.in_({"confirm_yes", "confirm_no"}))
async def handle_confirmation(callback: CallbackQuery):
    if not authorized_callback(callback):
        return
    sid = session_id(callback.from_user.id)
    answer = "نعم" if callback.data == "confirm_yes" else "لا"
    result = await chat_api(answer, sid)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(result["reply"])
    await callback.answer()


# --- Voice messages ---

@router.message(F.voice)
async def handle_voice(message: Message):
    if not authorized(message):
        return
    await message.answer("🎤 جاري معالجة الصوت...")
    bot = message.bot
    file = await bot.get_file(message.voice.file_id)
    file_data = io.BytesIO()
    await bot.download_file(file.file_path, file_data)
    file_bytes = file_data.getvalue()

    result = await api_post_file(
        "/ingest/file",
        file_bytes=file_bytes,
        filename="voice.ogg",
        content_type="audio/ogg",
        data={"context": "", "tags": "", "topic": ""},
    )

    analysis = result.get("analysis", {})

    # Handle error (e.g. transcription failed)
    if result.get("status") == "error":
        error_msg = analysis.get("error", "خطأ غير معروف")
        await message.answer(f"❌ فشل معالجة الصوت: {error_msg}")
        return

    # Get transcript text
    transcript = analysis.get("preview", "")
    if not transcript:
        await message.answer("❌ ما قدرت أفهم الكلام في المقطع.")
        return

    # Send transcript to chat API for an actual response
    sid = session_id(message.from_user.id)
    chat_result = await chat_api(transcript, sid)
    reply = chat_result.get("reply", "")

    keyboard = None
    if chat_result.get("pending_confirmation"):
        keyboard = confirmation_keyboard()

    reply_parts = [f"🎤 \"{transcript}\""]
    if reply:
        reply_parts.append(reply)
    await send_reply(message, "\n\n".join(reply_parts), keyboard=keyboard)


# --- Photo messages ---

@router.message(F.photo)
async def handle_photo(message: Message):
    if not authorized(message):
        return
    await message.answer("📸 جاري تحليل الصورة...")
    bot = message.bot
    # Get highest resolution photo
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_data = io.BytesIO()
    await bot.download_file(file.file_path, file_data)
    file_bytes = file_data.getvalue()

    context = message.caption or ""
    result = await api_post_file(
        "/ingest/file",
        file_bytes=file_bytes,
        filename="photo.jpg",
        content_type="image/jpeg",
        data={"context": context, "tags": "", "topic": ""},
    )

    # Handle duplicate files — still useful if user has a question or wants to update
    if result.get("status") == "duplicate":
        file_type = result.get("file_type", "")
        file_type_ar = _AR_FILE_TYPES.get(file_type, file_type)
        sid = session_id(message.from_user.id)
        # Photo search mode: search keywords in caption trigger similarity search
        _SEARCH_KEYWORDS = ("ابحث", "شبيه", "مشابه", "عندي زي", "similar", "search", "find")
        if context and any(kw in context for kw in _SEARCH_KEYWORDS):
            analysis_props = result.get("analysis", {})
            desc = analysis_props.get("description", "") or analysis_props.get("brief_description", "")
            if desc:
                try:
                    search_result = await api_post("/inventory/search-similar", json={"description": desc})
                    matches = search_result.get("results", [])
                    if matches:
                        lines = ["🔍 أغراض مشابهة:"]
                        for m in matches:
                            preview = m["text"].split("\n")[0] if "\n" in m["text"] else m["text"][:80]
                            lines.append(f"  • {preview}")
                        await send_reply(message, "\n".join(lines))
                    else:
                        await message.answer("ما لقيت أغراض مشابهة في المخزون.")
                except Exception as e:
                    logger.error("Photo search failed: %s", e)
                    await message.answer("❌ فشل البحث عن أغراض مشابهة.")
                return
        if context:
            # User has a caption/question — enrich with item name if inventory
            query = context
            if file_type == "inventory_item":
                file_hash = result.get("file_hash", "")
                if file_hash:
                    try:
                        item_data = await api_get(f"/inventory/by-file/{file_hash}")
                        item_name = item_data.get("name", "")
                        if item_name:
                            query = f"بخصوص {item_name}: {context}"
                    except Exception:
                        pass
            chat_result = await chat_api(query, sid)
            keyboard = None
            if chat_result.get("pending_confirmation"):
                keyboard = confirmation_keyboard()
            await send_reply(message, chat_result["reply"], keyboard=keyboard)
        elif file_type == "inventory_item":
            # Inventory item re-sent without caption — ask chat about it
            file_hash = result.get("file_hash", "")
            item_name = ""
            if file_hash:
                try:
                    item_data = await api_get(f"/inventory/by-file/{file_hash}")
                    item_name = item_data.get("name", "")
                except Exception:
                    pass
            if item_name:
                chat_result = await chat_api(f"وين {item_name}؟", sid)
                await send_reply(message, chat_result["reply"])
            else:
                await message.answer(f"📁 الملف موجود مسبقاً ({file_type_ar}).")
        else:
            await message.answer(f"📁 الملف موجود مسبقاً ({file_type_ar}).")
        return

    file_type = result.get("file_type", "unknown")
    analysis = result.get("analysis", {})
    file_type_ar = _AR_FILE_TYPES.get(file_type, file_type)

    # Build a structured summary and ask the LLM for an Arabic presentation
    analysis_text = json.dumps(analysis, ensure_ascii=False, indent=2)
    context_line = f"\nملاحظة المستخدم: \"{context}\"" if context else ""
    summary_prompt = (
        f"حللت صورة وهذي النتائج. لخصها بالعربي بسطرين إلى ثلاثة بالكثير.\n"
        f"ركز على: إيش الشي اللي في الصورة + المعلومات المهمة (اسم، ماركة، أرقام) + ملاحظة المستخدم.\n"
        f"لا توصف الخلفية أو الإضاءة أو التفاصيل غير المهمة.\n"
        f"نوع الملف: {file_type}\n"
        f"التحليل:\n{analysis_text}"
        f"{context_line}"
    )
    sid = session_id(message.from_user.id)
    # Skip fact extraction when auto_item already handled the item creation
    skip_facts = bool(result.get("auto_item"))
    try:
        summary_result = await api_post(
            "/chat/",
            json={
                "message": summary_prompt,
                "session_id": sid,
                "skip_fact_extraction": skip_facts,
            },
        )
        ar_summary = summary_result.get("reply", "")
    except Exception:
        ar_summary = ""

    reply_parts = [f"📁 التصنيف: {file_type_ar}"]

    if ar_summary:
        reply_parts.append(f"🔍 التحليل:\n{ar_summary}")
    else:
        # Fallback: show raw analysis with Arabic labels if chat fails
        detail_lines = []
        for key, val in analysis.items():
            if val is None or val == "":
                continue
            label = _AR_LABELS.get(key, key)
            if isinstance(val, list):
                val = "، ".join(str(v) for v in val) if val else "-"
            elif isinstance(val, dict):
                val = "، ".join(f"{k}: {v}" for k, v in val.items() if v)
            detail_lines.append(f"  • {label}: {val}")
        if detail_lines:
            reply_parts.append("🔍 التحليل:\n" + "\n".join(detail_lines))

    if result.get("auto_expense"):
        exp = result["auto_expense"]
        reply_parts.append(f"💰 مصروف تلقائي: {exp.get('amount', 0)} ريال — {exp.get('vendor', '')}")

    if result.get("auto_item"):
        item = result["auto_item"]
        reply_parts.append(f"📦 تم تسجيل: {item.get('name', '')} (الكمية: {item.get('quantity', 1)})")
        # If inventory_item created WITHOUT location (no caption), ask user
        if not (message.caption or "").strip() and not item.get("location"):
            sid = session_id(message.from_user.id)
            _pending_locations[sid] = {
                "item_name": item.get("name", ""),
                "created_at": time.monotonic(),
            }
            reply_parts.append("📍 وين حاطه؟ (أرسل المكان، مثلاً: السطح > الرف الثاني)")

    similar = result.get("similar_items", [])
    if similar:
        sim_lines = ["🔍 أغراض مشابهة في المخزون:"]
        for s in similar:
            preview = s["text"].split("\n")[0] if "\n" in s["text"] else s["text"][:80]
            sim_lines.append(f"  • {preview}")
        reply_parts.append("\n".join(sim_lines))

    reply_parts.append(
        f"✅ تم الحفظ: {result.get('chunks_stored', 0)} أجزاء، "
        f"{result.get('facts_extracted', 0)} حقائق"
    )
    await send_reply(message, "\n\n".join(reply_parts))


# --- Document messages ---

@router.message(F.document)
async def handle_document(message: Message):
    if not authorized(message):
        return
    doc = message.document
    await message.answer(f"📄 جاري معالجة الملف: {doc.file_name}...")
    bot = message.bot
    file = await bot.get_file(doc.file_id)
    file_data = io.BytesIO()
    await bot.download_file(file.file_path, file_data)
    file_bytes = file_data.getvalue()

    context = message.caption or ""
    result = await api_post_file(
        "/ingest/file",
        file_bytes=file_bytes,
        filename=doc.file_name or "document",
        content_type=doc.mime_type or "application/octet-stream",
        data={"context": context, "tags": "", "topic": ""},
    )

    reply_parts = [f"📁 {doc.file_name}"]
    file_type = result.get("file_type")
    if file_type:
        reply_parts.append(f"النوع: {file_type}")
    analysis = result.get("analysis", {})
    if analysis.get("summary"):
        reply_parts.append(f"📋 {analysis['summary']}")
    reply_parts.append(
        f"✅ تم الحفظ ({result.get('chunks_stored', 0)} أجزاء، "
        f"{result.get('facts_extracted', 0)} حقائق)"
    )
    await send_reply(message, "\n".join(reply_parts))


# --- Text messages (catch-all) ---

@router.message(F.text)
async def handle_text(message: Message):
    if not authorized(message):
        return
    sid = session_id(message.from_user.id)

    # Check for pending location update (from captionless inventory photo)
    if sid in _pending_locations:
        pending = _pending_locations[sid]
        age = time.monotonic() - pending["created_at"]
        if age <= _PENDING_LOCATION_TTL:
            _pending_locations.pop(sid)
            location = message.text.strip()
            item_name = pending["item_name"]
            try:
                await api_put(
                    f"/inventory/item/{item_name}/location",
                    json={"location": location},
                )
                await message.answer(f"📍 تم تحديث مكان {item_name}: {location}")
            except Exception as e:
                logger.error("Failed to update item location: %s", e)
                await message.answer("❌ ما قدرت أحدث المكان، حاول مرة ثانية.")
            return
        else:
            # Expired — remove and proceed normally
            _pending_locations.pop(sid)

    # Use streaming for regular chat
    placeholder = await message.answer("...")
    stream_result = await chat_api_stream(message.text, sid, placeholder)
    reply_text = stream_result.get("text", "")
    pending = stream_result.get("pending_confirmation", False)

    if not reply_text.strip():
        try:
            await placeholder.delete()
        except Exception:
            pass
        # Fallback to non-streaming
        result = await chat_api(message.text, sid)
        keyboard = None
        if result.get("pending_confirmation"):
            keyboard = confirmation_keyboard()
        await send_reply(message, result["reply"], keyboard=keyboard)
    elif pending:
        # Streaming returned a confirmation prompt — add inline keyboard
        try:
            await placeholder.edit_reply_markup(reply_markup=confirmation_keyboard())
        except Exception:
            # If edit fails, send a new message with keyboard
            await message.answer("⚠️ تأكيد مطلوب:", reply_markup=confirmation_keyboard())


# --- Error handler ---

@router.error()
async def error_handler(event: types.ErrorEvent):
    """Catch unhandled exceptions and notify the user."""
    logger.exception("Unhandled error: %s", event.exception)
    update = event.update
    msg = None
    if update.message:
        msg = update.message
    elif update.callback_query and update.callback_query.message:
        msg = update.callback_query.message
    if msg:
        try:
            await msg.answer("❌ حصل خطأ أثناء المعالجة. حاول مرة ثانية بعد شوي.")
        except Exception:
            pass


# --- Proactive Formatters ---


def format_morning_summary(data: dict) -> str:
    parts = ["صباح الخير! هذي خطة يومك:"]
    plan = data.get("daily_plan", "")
    if plan and plan != "No actionable items for today.":
        parts.append(plan)
    else:
        parts.append("ما عندك شي مجدول اليوم.")

    alerts = data.get("spending_alerts")
    if alerts:
        parts.append(f"\n{alerts}")

    tb = data.get("timeblock_suggestion")
    if tb and tb.get("blocks"):
        energy_ar = {"normal": "عادي", "tired": "متعب", "energized": "نشيط"}
        profile = energy_ar.get(tb.get("energy_profile", ""), tb.get("energy_profile", ""))
        lines = [f"\nجدول المهام المقترح ({profile}):"]
        for b in tb["blocks"]:
            start = b["start_time"][-8:-3]
            end = b["end_time"][-8:-3]
            lines.append(f"  [{start}-{end}] {b['task_title']}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def format_noon_checkin(data: dict) -> str:
    overdue = data.get("overdue_reminders", [])
    if not overdue:
        return ""
    lines = ["تذكيرات متأخرة:"]
    for r in overdue:
        priority = f" [أولوية: {r['priority']}]" if r.get("priority") and r["priority"] >= 3 else ""
        lines.append(f"  - {r['title']} (كان المفروض: {r['due_date']}){priority}")
    return "\n".join(lines)


def format_evening_summary(data: dict) -> str:
    parts = ["مساء الخير! ملخص يومك:"]

    completed = data.get("completed_today", [])
    if completed:
        items = "\n".join(f"  - {c}" for c in completed)
        parts.append(f"أنجزت اليوم ({len(completed)}):\n{items}")
    else:
        parts.append("ما أنجزت شي مسجل اليوم.")

    tomorrow = data.get("tomorrow_reminders", [])
    if tomorrow:
        items = "\n".join(f"  - {r['title']} ({r['due_date']})" for r in tomorrow)
        parts.append(f"تذكيرات بكرة ({len(tomorrow)}):\n{items}")

    return "\n\n".join(parts)


def format_stalled_projects(data: dict) -> str:
    projects = data.get("stalled_projects", [])
    if not projects:
        return ""
    days = data.get("days_threshold", 14)
    lines = [f"مشاريع متوقفة (>{days} يوم):"]
    for p in projects:
        lines.append(f"  - {p['name']} (آخر نشاط: {p['last_activity']}, {p['task_count']} مهام)")
    return "\n".join(lines)


def format_old_debts(data: dict) -> str:
    debts = data.get("old_debts", [])
    if not debts:
        return ""
    days = data.get("days_threshold", 30)
    lines = [f"ديون قديمة (>{days} يوم):"]
    for d in debts:
        reason = f" — {d['reason']}" if d.get("reason") else ""
        lines.append(f"  - {d['person']}: {d['amount']:.0f} ريال{reason}")
    return "\n".join(lines)


# --- Proactive Jobs ---


async def job_morning_summary(bot: Bot):
    try:
        data = await api_get("/proactive/morning-summary")
        plan = data.get("daily_plan", "")

        if plan and plan != "No actionable items for today.":
            try:
                fmt = await api_post(
                    "/proactive/format-reminders",
                    json={"raw_text": plan, "context": "morning"},
                )
                text = fmt.get("formatted", "")
            except Exception:
                text = format_morning_summary(data)
        else:
            text = "صباح الخير! ما عندك شي مجدول اليوم ☀️"

        alerts = data.get("spending_alerts")
        if alerts:
            text += f"\n\n💰 {alerts}"

        for part in split_message(text):
            await bot.send_message(chat_id=settings.tg_chat_id, text=part)
        logger.info("Morning summary sent")
    except Exception as e:
        logger.error("Morning summary job failed: %s", e)


async def job_noon_checkin(bot: Bot):
    try:
        data = await api_get("/proactive/noon-checkin")
        text = format_noon_checkin(data)
        if text:
            for part in split_message(text):
                await bot.send_message(chat_id=settings.tg_chat_id, text=part)
            logger.info("Noon check-in sent")
    except Exception as e:
        logger.error("Noon check-in job failed: %s", e)


async def job_evening_summary(bot: Bot):
    try:
        data = await api_get("/proactive/evening-summary")
        text = format_evening_summary(data)
        for part in split_message(text):
            await bot.send_message(chat_id=settings.tg_chat_id, text=part)
        logger.info("Evening summary sent")
    except Exception as e:
        logger.error("Evening summary job failed: %s", e)


async def job_check_reminders(bot: Bot):
    try:
        data = await api_get("/proactive/due-reminders")
        reminders = data.get("due_reminders", [])
        if not reminders:
            return

        # 1. Call LLM to format all reminders as one message
        try:
            fmt = await api_post(
                "/proactive/format-reminders",
                json={"reminders": reminders, "context": "due"},
            )
            text = fmt.get("formatted", "")
        except Exception:
            text = "⏰ تذكيراتك:\n\n" + "\n".join(
                f"{'🔴' if (r.get('priority') or 0) >= 4 else '🔵'} {r['title']}"
                for r in reminders
            )

        # 2. Send one batched message
        for part in split_message(text):
            await bot.send_message(chat_id=settings.tg_chat_id, text=part)

        # 3. Mark notified + advance recurring
        for r in reminders:
            try:
                await api_post("/proactive/mark-notified", json={"title": r["title"]})
            except Exception:
                pass
            recurrence = r.get("recurrence")
            if recurrence and recurrence in ("daily", "weekly", "monthly", "yearly"):
                try:
                    await api_post(
                        "/proactive/advance-reminder",
                        json={"title": r["title"], "recurrence": recurrence},
                    )
                except Exception:
                    pass

        logger.info("Sent %d due reminder(s) (formatted)", len(reminders))
    except Exception as e:
        logger.error("Reminder check job failed: %s", e)


async def job_daily_backup(bot: Bot):
    """Daily automated backup with Telegram notification."""
    try:
        data = await api_post("/backup/create", timeout=300.0)
        sizes = data.get("sizes", {})
        total_kb = sum(sizes.values()) / 1024
        ts = data.get("timestamp", "?")
        removed = data.get("old_backups_removed", 0)
        text = f"نسخة احتياطية تلقائية: {ts} ({total_kb:.0f} KB)"
        if removed:
            text += f" — حذف {removed} نسخ قديمة"
        await bot.send_message(chat_id=settings.tg_chat_id, text=text)
        logger.info("Daily backup completed: %s", ts)
    except Exception as e:
        logger.error("Daily backup job failed: %s", e)
        try:
            await bot.send_message(chat_id=settings.tg_chat_id, text=f"فشل النسخ الاحتياطي: {e}")
        except Exception:
            pass


async def job_smart_alerts(bot: Bot):
    try:
        parts = []

        stalled = await api_get(
            "/proactive/stalled-projects",
            params={"days": settings.proactive_stalled_days},
        )
        stalled_text = format_stalled_projects(stalled)
        if stalled_text:
            parts.append(stalled_text)

        debts = await api_get(
            "/proactive/old-debts",
            params={"days": settings.proactive_old_debt_days},
        )
        debts_text = format_old_debts(debts)
        if debts_text:
            parts.append(debts_text)

        if parts:
            text = "\n\n".join(parts)
            for part in split_message(text):
                await bot.send_message(chat_id=settings.tg_chat_id, text=part)
            logger.info("Smart alerts sent")
    except Exception as e:
        logger.error("Smart alerts job failed: %s", e)


# --- Main ---

async def main():
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set. Exiting.")
        sys.exit(1)
    if not settings.tg_chat_id:
        logger.warning("TG_CHAT_ID not set — bot will not respond to anyone.")

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    global _scheduler
    scheduler = None
    if settings.proactive_enabled:
        scheduler = AsyncIOScheduler()
        _scheduler = scheduler
        scheduler.add_job(
            job_morning_summary, CronTrigger(hour=settings.proactive_morning_hour), args=[bot], id="morning"
        )
        scheduler.add_job(
            job_noon_checkin, CronTrigger(hour=settings.proactive_noon_hour), args=[bot], id="noon"
        )
        scheduler.add_job(
            job_evening_summary, CronTrigger(hour=settings.proactive_evening_hour), args=[bot], id="evening"
        )
        scheduler.add_job(
            job_check_reminders,
            IntervalTrigger(minutes=settings.proactive_reminder_check_minutes),
            args=[bot],
            id="reminders",
        )
        scheduler.add_job(
            job_smart_alerts,
            IntervalTrigger(hours=settings.proactive_alert_check_hours),
            args=[bot],
            id="alerts",
        )

        # Daily backup job
        if settings.backup_enabled:
            scheduler.add_job(
                job_daily_backup, CronTrigger(hour=settings.backup_hour), args=[bot], id="backup"
            )
            logger.info("Daily backup scheduled at %d:00 local", settings.backup_hour)

        scheduler.start()
        logger.info(
            "Scheduler started with jobs (morning=%d:00, noon=%d:00, evening=%d:00 local)",
            settings.proactive_morning_hour,
            settings.proactive_noon_hour,
            settings.proactive_evening_hour,
        )

    try:
        logger.info("Telegram bot starting (polling)...")
        await dp.start_polling(bot)
    finally:
        if scheduler:
            scheduler.shutdown()
            logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
