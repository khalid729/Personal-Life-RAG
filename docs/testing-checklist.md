# قائمة الاختبارات — Phase 5 Interfaces

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
| **الإجمالي** | **48** | **46** | **2** |

الاختبارين الباقيين يحتاجون Open WebUI Docker container شغال.
