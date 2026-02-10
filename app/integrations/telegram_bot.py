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
        "/inventory — المخزون والأغراض"
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


@router.message(Command("inventory"))
async def cmd_inventory(message: Message):
    if not authorized(message):
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

    # Handle duplicate files
    if result.get("status") == "duplicate":
        file_type_ar = _AR_FILE_TYPES.get(result.get("file_type", ""), result.get("file_type", ""))
        await message.answer(f"📁 الملف موجود مسبقاً ({file_type_ar}) — ما يحتاج يتخزن مرة ثانية.")
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
                await api_post(
                    f"/inventory/item/{item_name}/location",
                    json={"location": location},
                    timeout=CHAT_TIMEOUT,
                )
                await message.answer(f"📍 تم تحديث مكان {item_name}: {location}")
            except Exception as e:
                logger.error("Failed to update item location: %s", e)
                await message.answer("❌ ما قدرت أحدث المكان، حاول مرة ثانية.")
            return
        else:
            # Expired — remove and proceed normally
            _pending_locations.pop(sid)

    result = await chat_api(message.text, sid)

    keyboard = None
    if result.get("pending_confirmation"):
        keyboard = confirmation_keyboard()

    await send_reply(message, result["reply"], keyboard=keyboard)


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


def format_due_reminder(reminder: dict) -> str:
    title = reminder.get("title", "")
    desc = reminder.get("description", "")
    priority = reminder.get("priority")
    lines = [f"تذكير: {title}"]
    if desc:
        lines.append(desc)
    if priority and priority >= 3:
        lines.append(f"[أولوية: {priority}]")
    return "\n".join(lines)


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
        text = format_morning_summary(data)
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
        for r in reminders:
            text = format_due_reminder(r)
            await bot.send_message(chat_id=settings.tg_chat_id, text=text)
            # Advance recurring reminders to next due date
            recurrence = r.get("recurrence")
            if recurrence and recurrence in ("daily", "weekly", "monthly", "yearly"):
                try:
                    await api_post(
                        "/proactive/advance-reminder",
                        json={"title": r["title"], "recurrence": recurrence},
                    )
                    logger.info("Advanced recurring reminder: %s", r["title"])
                except Exception as e:
                    logger.warning("Failed to advance reminder '%s': %s", r["title"], e)
        if reminders:
            logger.info("Sent %d due reminder(s)", len(reminders))
    except Exception as e:
        logger.error("Reminder check job failed: %s", e)


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

    scheduler = None
    if settings.proactive_enabled:
        scheduler = AsyncIOScheduler()
        tz_offset = settings.timezone_offset_hours
        morning_utc = (settings.proactive_morning_hour - tz_offset) % 24
        noon_utc = (settings.proactive_noon_hour - tz_offset) % 24
        evening_utc = (settings.proactive_evening_hour - tz_offset) % 24

        scheduler.add_job(
            job_morning_summary, CronTrigger(hour=morning_utc), args=[bot], id="morning"
        )
        scheduler.add_job(
            job_noon_checkin, CronTrigger(hour=noon_utc), args=[bot], id="noon"
        )
        scheduler.add_job(
            job_evening_summary, CronTrigger(hour=evening_utc), args=[bot], id="evening"
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
        scheduler.start()
        logger.info(
            "Scheduler started with 5 jobs (morning=%d:00, noon=%d:00, evening=%d:00 local)",
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
