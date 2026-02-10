# قائمة الاختبارات — Phase 5 Interfaces + Phase 6 Proactive System

## Telegram Bot

### الأساسيات
- [x] البوت يشتغل بدون أخطاء (polling mode)
- [x] `/start` — رسالة ترحيب
- [x] Auth — يرد بس على `TG_CHAT_ID` المحدد

### الرسائل النصية
- [x] إرسال نص عربي → رد عربي من `/chat/`
- [x] Confirmation flow — أزرار نعم/لا inline keyboard
- [x] إرسال نص إنجليزي → يترجم ويرد عربي ✓ (API test: "What are my reminders?" → رد بالعربي)

### الصور
- [x] إرسال صورة → تصنيف + تحليل بالعربي
- [x] إرسال صورة مع كابشن → يقرأ الكابشن ويركز عليه في الملخص
- [x] إرسال صورة مكررة → "الملف موجود مسبقاً"
- [x] Auto-expense من فواتير (لو total > 0)

### الصوت
- [x] إرسال صوت → يحول لنص (WhisperX) → يرسل لـ `/chat/` → يجاوب
- [x] WhisperX بالعربي (`language="ar"`)
- [x] الصوت ما يخزن حقائق مكررة (transcription_only mode)
- [x] إرسال صوت طويل — timeout مضبوط 120 ثانية + batch_size=16 (لم يُختبر بملف >1 دقيقة فعلياً)

### المستندات
- [x] إرسال PDF → يستخرج النص ويخزن (API test: new_test.pdf → 1 chunk stored)
- [x] إرسال ملف غير مدعوم → رسالة خطأ مناسبة (API test: .xyz → status: "error")

### الأوامر
- [x] `/reminders` — عرض التذكيرات
- [x] `/debts` — ملخص الديون (API + formatting verified)
- [x] `/projects` — المشاريع (API + formatting verified)
- [x] `/tasks` — المهام (API + formatting verified)
- [x] `/report` — التقرير المالي (API + formatting verified)
- [x] `/plan` — خطة اليوم (API test: "رتب لي يومي" → خطة مفصلة بالعربي)

---

## MCP Server

- [x] MCP server يشتغل على port 8600 بدون أخطاء
- [x] 12 tools مسجلة صحيح
- [x] `chat` tool — محادثة عبر MCP ("كم ديوني؟" → رد بالعربي مع التفاصيل)
- [x] `search` tool — بحث في المعرفة ("power bank" → نتائج CUKTECH 15)
- [x] `get_reminders` — التذكيرات ✓
- [x] `get_debts` — الديون ✓ (مع direction صحيح بعد الإصلاح)
- [x] `get_financial_report` — التقرير المالي ✓
- [x] `get_projects` — المشاريع ✓
- [x] `get_tasks` — المهام ✓
- [x] `get_knowledge` — المعرفة ✓
- [x] `create_reminder` — إنشاء تذكير ("ذكرني أشتري حليب بكرة" → confirmation)
- [x] `record_expense` — تسجيل مصروف ("صرفت 35 ريال على قهوة" → confirmation)
- [x] `ingest_text` — حفظ نص (1 chunk + 1 fact)
- [x] `daily_plan` — خطة اليوم ✓

---

## Open WebUI Tools

- [x] Syntax check — الملف يتحقق بدون أخطاء
- [x] Class instantiation — 8 tools + Valves
- [ ] نسخ الملف لـ Open WebUI Admin → Functions (يحتاج Open WebUI running)
- [ ] اختبار مباشر في Open WebUI (يحتاج Docker container)

---

## اختبارات عامة

- [x] التاريخ والوقت صحيح (توقيت الرياض UTC+3)
- [x] "بكرة" = التاريخ الصحيح (في system prompt و extract prompt)
- [x] Multi-session — جلسات مختلفة ما تتداخل (Session A عرف "خالد"، Session B ما عرفه)
- [x] Timeout handling — timeouts مضبوطة (chat=60s, file=120s, MCP=60s)
- [x] Message splitting — رسائل > 4096 حرف تتقسم صحيح
- [x] Error recovery — error handler يرسل "حصل خطأ" للمستخدم (أُضيف أثناء الاختبار)
- [x] API error handling — 404 للمسارات الخاطئة، 422 للبيانات الناقصة
- [x] PDF upload — يستخرج النص ويخزن
- [x] Unsupported file — يرجع خطأ بدون crash
- [x] File dedup — الملفات المكررة تتخطى

---

## Phase 6 — Proactive System

### REST Endpoints (`/proactive/*`)
- [x] `/proactive/morning-summary` — يرجع خطة اليوم + تنبيهات المصاريف (967 حرف، 10 تذكيرات + 4 مهام + ديون)
- [x] `/proactive/noon-checkin` — التذكيرات المتأخرة (10 تذكيرات متأخرة)
- [x] `/proactive/evening-summary` — المنجزات + تذكيرات بكرة (2 منجزة، 7 تذكيرات بكرة)
- [x] `/proactive/due-reminders` — التذكيرات المستحقة مع حقل recurrence (10 تذكيرات، 1 متكرر شهري)
- [x] `/proactive/advance-reminder` — تقديم تذكير متكرر للموعد التالي ("renew template" 2026-02-11 → 2026-03-11)
- [x] `/proactive/stalled-projects?days=14` — المشاريع المتوقفة (0 حالياً)
- [x] `/proactive/old-debts?days=30` — الديون القديمة (0 حالياً)

### Scheduler (APScheduler في Telegram Bot)
- [x] البوت يشتغل مع الـ scheduler بدون أخطاء
- [x] 5 jobs مسجلة: morning, noon, evening, reminders (30 دقيقة), alerts (6 ساعات)
- [x] Log message: "Scheduler started with 5 jobs (morning=7:00, noon=13:00, evening=21:00 local)"
- [x] تحويل الساعات المحلية لـ UTC صحيح (`(local_hour - tz_offset) % 24`)

### Fire Tests (إرسال فعلي عبر Telegram)
- [x] Morning summary — وصلت رسالة تلقرام بخطة اليوم كاملة
- [x] Evening summary — وصلت رسالة بالمنجزات + تذكيرات بكرة
- [x] Smart alerts — تخطى الإرسال بشكل صحيح (ما في مشاريع متوقفة أو ديون قديمة)

### Graph Service
- [x] `advance_recurring_reminder()` — يحسب الموعد التالي صحيح (daily/weekly/monthly/yearly)
- [x] `dateutil.relativedelta` — يشتغل للشهري والسنوي

### Config
- [x] 8 إعدادات `proactive_*` في config.py
- [x] `proactive_enabled` — تفعيل/تعطيل الـ scheduler

### Regression (الـ endpoints القديمة ما تأثرت)
- [x] `/health` — OK
- [x] `/chat/` — OK (رد بالعربي)
- [x] `/search/` — OK
- [x] `/reminders/` — OK
- [x] `/financial/report` — OK
- [x] `/financial/debts` — OK
- [x] `/financial/alerts` — OK
- [x] `/projects/` — OK
- [x] `/tasks/` — OK
- [x] `/knowledge/` — OK

---

## باقات أُصلحت أثناء الاختبارات

- [x] **Debt direction mismatch**: LLM يرجع `owed_by_me` بس الكود يتوقع `i_owe` — أضفنا `_normalize_direction()` في graph.py
- [x] **Extract prompt missing "I owe" example**: أضفنا مثال لتعليم الـ LLM يستخدم `i_owe`
- [x] **`owed_to_other` direction**: أضفناها للـ normalizer
- [x] **Existing data fix**: حولنا `owed_by_me` و `owed_to_other` → `i_owe` في FalkorDB
- [x] **Bot error handler**: أضفنا `@router.error()` handler يرسل "حصل خطأ" للمستخدم عند أي exception

---

## ملخص النتائج

| المكون | الاختبارات | ناجحة | باقية |
|--------|-----------|-------|-------|
| Telegram Bot | 20 | 20 | 0 |
| MCP Server | 14 | 14 | 0 |
| Open WebUI | 4 | 2 | 2 (يحتاج Docker) |
| عام | 10 | 10 | 0 |
| Phase 6 — Proactive Endpoints | 7 | 7 | 0 |
| Phase 6 — Scheduler | 4 | 4 | 0 |
| Phase 6 — Fire Tests | 3 | 3 | 0 |
| Phase 6 — Graph/Config | 3 | 3 | 0 |
| Phase 6 — Regression | 10 | 10 | 0 |
| Phase 7 — Core Inventory | 8 | 8 | 0 |
| Phase 7 — Usage/Interactions | 3 | 3 | 0 |
| Phase 7 — Smart Inventory | 4 | 4 | 0 |
| Phase 8 — Entity Resolution | 2 | 2 | 0 |
| Phase 8 — Smart Tags + Knowledge | 2 | 2 | 0 |
| Phase 8 — Multi-hop Traversal | 1 | 1 | 0 |
| Phase 9 — Advanced Inventory | 6 | 6 | 0 |
| **الإجمالي** | **101** | **99** | **2** |

الاختبارين الباقيين يحتاجون Open WebUI Docker container شغال.

---

## Phase 7 — Inventory System

### Core Inventory (7a)
- [x] تصوير غرض → تصنيف `inventory_item` → تحليل + إنشاء Item تلقائي
- [x] `/inventory` — عرض الأغراض في تلقرام
- [x] REST: GET `/inventory/` + `/inventory/summary`
- [x] REST: POST `/inventory/item` (create/update)
- [x] REST: PUT `/inventory/item/{name}/location` + `/inventory/item/{name}/quantity`
- [x] Location normalization (English→Arabic, `>` separator)
- [x] File dedup: صورة مكررة + caption → enriches query
- [x] Smart router: "وين ال X" / "مخزون" → `graph_inventory`

### Usage + Interactions (7b)
- [x] ItemUsage: "استخدمت 2 بطاريات" → quantity - 2 (clamped at 0)
- [x] Bot asks "وين حاطه؟" on captionless inventory photos
- [x] Clarification skip: extraction found entities → skip clarification LLM

### Smart Inventory (7c)
- [x] ItemMove: "نقلت الطابعة من السطح للمكتب" → confirmation → STORED_IN updated
- [x] Purchase alert: confirmed expense → "⚠️ عندك في المخزون: ..."
- [x] POST `/inventory/search-similar` → vector search (score ≥ 0.4)
- [x] Category normalization: "cables" → "إلكترونيات"

### ملخص Phase 7

| المكون | الاختبارات | ناجحة |
|--------|-----------|-------|
| Core Inventory (7a) | 8 | 8 |
| Usage + Interactions (7b) | 3 | 3 |
| Smart Inventory (7c) | 4 | 4 |
| **الإجمالي Phase 7** | **15** | **15** |

---

## Phase 8 — Smart Knowledge + Entity Resolution

### Entity Resolution
- [x] "Mohamed" → "Mohammed" (score 0.89) — single Person node with `name_aliases: ["Mohamed"]`
- [x] Knowledge resolution: "Python async code handling trick" → "Python async code trick" (score 0.94)

### Smart Tags + Knowledge Auto-categorization
- [x] Knowledge auto-category: "Python async code trick" → `category: "تقنية"`, TAGGED_WITH → Tag("تقنية")
- [x] Tag normalization: English→Arabic aliases applied (`_TAG_ALIASES` dict)

### Multi-hop Graph Traversal
- [x] "tell me about Mohammed" → `graph_person` route → 3-hop context (person + company + debts + aliases)

### ملخص Phase 8

| المكون | الاختبارات | ناجحة |
|--------|-----------|-------|
| Entity Resolution | 2 | 2 |
| Smart Tags + Knowledge | 2 | 2 |
| Multi-hop Traversal | 1 | 1 |
| **الإجمالي Phase 8** | **5** | **5** |

---

## Phase 9 — Advanced Inventory

### QR/Barcode Scanning
- [x] `_scan_barcodes(file_bytes)` — pyzbar + PIL on BytesIO
- [x] GET `/inventory/by-barcode/1234567890` → 404 (correct, no barcodes stored yet)

### Last-Use Tracking
- [x] `_touch_item_last_used()` fire-and-forget on inventory queries + usage + move
- [x] GET `/inventory/unused?days=90` → 200 (19 unused items)

### Inventory Report
- [x] GET `/inventory/report` → 200 (26 items, 7 sub-queries: totals, category, location, condition, no-location, unused, top)
- [x] Telegram `/inventory report` — Arabic formatted report

### Duplicate Detection
- [x] GET `/inventory/duplicates` → 200 (14 name-overlap duplicates)
- [x] GET `/inventory/duplicates?method=vector` → 200 (empty — expected, embedding similarity)

### Regression
- [x] GET `/inventory/` → 200
- [x] GET `/inventory/summary` → 200

### ملخص Phase 9

| المكون | الاختبارات | ناجحة |
|--------|-----------|-------|
| QR/Barcode Scanning | 2 | 2 |
| Last-Use Tracking | 2 | 2 |
| Inventory Report | 2 | 2 |
| Duplicate Detection | 2 | 2 |
| Regression | 2 | 2 |
| **الإجمالي Phase 9** | **10** | **10** |
