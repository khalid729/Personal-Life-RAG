# تحسينات مستقبلية

## ~~1. Smart Tags بـ Vector Dedup~~ ✅ (Phase 8)
تم التنفيذ:
- `_TAG_ALIASES` dict + `_normalize_tag()` لتحويل English→Arabic
- `upsert_tag()` يبحث بالـ Qdrant عن tags متشابهة (threshold 0.85+) → يستخدم الموجود
- `tag_entity()` يربط أي entity بـ Tag عبر `TAGGED_WITH` في FalkorDB
- Knowledge auto-tagging: `_guess_knowledge_category()` → TAGGED_WITH تلقائي

---

## 2. تحسين الملخص العربي للصور
**المشكلة**: الملخص أحياناً يوصف الخلفية والإضاءة بدل ما يركز على الشي المهم.

**الحل**:
- تحسين Vision prompt ليركز على المنتج/الشي الرئيسي
- أو post-filter على الملخص يشيل الوصف غير المهم

---

## ~~3. Entity Resolution / Dedup~~ ✅ (Phase 8)
تم التنفيذ:
- `resolve_entity_name()` يبحث بالـ Qdrant عن كيانات مشابهة (Person: 0.85، default: 0.80)
- `_store_alias()` يحفظ الأسماء البديلة على الـ canonical node (`name_aliases` list)
- مدمج في: upsert_person/project/company/topic, _create_generic (Knowledge/Topic), relationship targets

---

## ~~4. Recurring Reminder Execution~~ ✅ (Phase 6)
~~**المشكلة**: التذكيرات المتكررة تتخزن بس ما تنفذ تلقائي.~~

تم التنفيذ: APScheduler يفحص كل 30 دقيقة → `advance_recurring_reminder()` يقدم التاريخ التالي.

---

## ~~5. Proactive System~~ ✅ (Phase 6)
تم التنفيذ بالكامل:
- ملخص صباحي (7:00), check-in الظهر (13:00), ملخص المساء (21:00)
- تنبيهات ذكية (ديون قديمة، مشاريع متوقفة)
- 7 REST endpoints + 5 APScheduler jobs

---

## ~~6. Streaming Responses~~ ✅ (Phase 11)
تم التنفيذ:
- `chat_stream()` في LLM — يقرأ SSE من vLLM ويرسل token chunks
- `POST /chat/stream` — NDJSON streaming endpoint
- Telegram streaming: يعدّل رسالة placeholder كل ثانية مع tokens جديدة
- `_prepare_context()` — مشتركة بين sync و streaming لإعادة استخدام الكود

---
---

# مشاكل مستعصية وحلولها — Phase 5 Testing

## 1. PyTorch 2.6 + WhisperX: `weights_only` Error
**المشكلة**: PyTorch 2.6 غيّر default من `weights_only=False` إلى `True`. WhisperX/pyannote checkpoints تستخدم `omegaconf` types اللي مو في safe list.

**المحاولات الفاشلة**:
1. `torch.serialization.add_safe_globals([ListConfig, DictConfig])` — حلت نوع بس طلع نوع ثاني (`ContainerMetadata`)، ثم `list` builtin... لا نهاية
2. Monkey-patch `torch.load = _patched_load` — ما وصل للمكتبات لأنها تحفظ reference لـ `torch.load` عند الـ import
3. `torch.load.__kwdefaults__["weights_only"] = False` — ما نفع لأن Lightning تمرر `weights_only=None` explicitly (مو missing)
4. Patch كل `sys.modules` اللي فيها reference لـ `torch.load` — بعضها ما انمسك

**الحل النهائي**: Lightning's `_load()` تمرر `weights_only=None` explicitly لـ `torch.load`. و PyTorch 2.6 يعامل `None` كـ `True`. الحل: wrap `torch.load` ونحول `None` → `False`:
```python
_orig = torch.load.__wrapped__ if hasattr(torch.load, "__wrapped__") else torch.load
def _patched_load(*a, **kw):
    if kw.get("weights_only") is None:
        kw["weights_only"] = False
    return _orig(*a, **kw)
torch.load = _patched_load
```
**السبب**: `setdefault("weights_only", False)` ما يشتغل لأن المفتاح موجود بقيمة `None`. لازم نفحص `is None` explicitly.

---

## 2. WhisperX `UnboundLocalError: model`
**المشكلة**: `cannot access local variable 'model' where it is not associated with a value`

**السبب**: `finally` block فيه `del model` لكن لو `whisperx.load_model()` رمى exception، `model` ما تعرّف أصلاً.

**الحل**: تهيئة `model = None` و `audio = None` قبل `try`، وفحص `if model is not None` قبل `del`.

---

## 3. FalkorDB Cypher: CREATE inline props
**المشكلة**: `_create_generic` و `create_idea` يستخدمون `n.{k} = ${k}` داخل `CREATE ({...})` — هذا syntax الـ SET clause مو الـ CREATE.

**الحل**: `{k}: ${k}` للـ inline props داخل CREATE.
```cypher
-- خطأ:
CREATE (n:Label {n.key = $val})
-- صح:
CREATE (n:Label {key: $val})
```

---

## 4. FalkorDB Primitive Types
**المشكلة**: LLM يستخرج properties من نوع `dict` أو `list[dict]` — FalkorDB يقبل بس primitive types.

**الحل**: في `_create_generic`، نحول `dict` → `json.dumps(str)` و `list[dict]` → `list[str]` قبل التخزين.

---

## 5. التاريخ والوقت الخاطئ
**المشكلة**: النموذج يقول "بكرة الجمعة 4 أبريل 2025" بدل التاريخ الصحيح.

**الأسباب (3 طبقات)**:
1. **System prompt** ما فيه التاريخ → النموذج يخمّن
2. **Extract prompt** ما فيه التاريخ → "بكرة" تتحول لتاريخ عشوائي عند استخراج الحقائق
3. **Working memory** فيها ردود قديمة بتواريخ غلط → النموذج يكررها
4. **UTC vs local time** — السيرفر يحسب UTC بس المستخدم في UTC+3

**الحل**:
- إضافة التاريخ + الوقت + "بكرة" في system prompt مع تعليمة واضحة
- إضافة التاريخ في extract prompt
- استخدام `timezone_offset_hours` من config (Asia/Riyadh = UTC+3)
- مسح الـ working memory القديمة اللي فيها تواريخ غلط

---

## 6. Photo Reply بالإنجليزي
**المشكلة**: تحليل الصور يرجع بالإنجليزي رغم إن الخطة "خزن بالإنجليزي، كلّم بالعربي".

**المحاولات**:
1. Arabic labels dictionary — ترجم أسماء الحقول بس القيم بقت إنجليزية
2. إرسال التحليل لـ `/chat/` — ترجمة كاملة للعربي ✓

**الحل النهائي**: بعد تحليل الصورة، نرسل النتائج + كابشن المستخدم لـ `/chat/` endpoint اللي يلخص بالعربي بـ 2-3 أسطر مركزة.

---

## 7. تخزين مكرر للملفات
**المشكلة**: نفس الصورة تتخزن عدة مرات (8 Knowledge nodes + ~7 vector chunks).

**الحل**: Content-addressed dedup — `find_file_by_hash()` في GraphService يفحص SHA256 hash. لو موجود → يرجع `status: "duplicate"` بدون إعادة معالجة.

---

## 8. Voice = تخزين بدون رد
**المشكلة**: الصوت يروح لـ `/ingest/file` اللي يخزن بس — ما يجاوب على سؤال المستخدم.

**الحل**: Voice handler يرسل لـ `/ingest/file` للتحويل فقط (transcription_only)، ثم يرسل النص لـ `/chat/` للرد + استخراج الحقائق. مسار واحد بدون تكرار.

---

## 9. Debt Direction Mismatch
**المشكلة**: الـ LLM يستخرج `direction: "owed_by_me"` أو `"owed_to_other"` للديون اللي عليك، بس الكود يتوقع `"i_owe"`. النتيجة: كل الديون تنحسب كأنها "لك" بدل "عليك"، والمجاميع غلط.

**السبب**: الـ extract prompt فيه مثال واحد بس لـ `"owed_to_me"` (شخص يدينك)، وما فيه مثال لـ "أنا أدين شخص" — فالـ LLM يخترع قيم مثل `"owed_by_me"`.

**الحل**:
1. `_normalize_direction()` في graph.py — يحول كل الأشكال (`owed_by_me`, `owed_to_other`, `i owe`) → `"i_owe"`
2. إضافة مثال "I owe Fahd 800 riyals" → `direction: "i_owe"` في extract prompt
3. إصلاح البيانات الموجودة في FalkorDB

---

## 10. Open WebUI: LLM يتجاهل store_document
**المشكلة**: لما المستخدم يرفع PDF في Open WebUI، الفلتر يقول للـ LLM "استدعي store_document" بس الـ LLM:
- أحياناً ما يستدعي الأداة أصلاً
- يرسل ملخص بدل النص الكامل
- يستخدم الوقت الحالي بدل أوقات المستند

**الحل**: إعادة كتابة الفلتر (v2.0) — يعالج الملفات مباشرة بدون الاعتماد على الـ LLM:
1. `_extract_files()` يقرأ الملفات من `body["files"][0]["file"]["path"]` (بنية Open WebUI)
2. `_process_file_via_api()` يقرأ الملف من مسار Docker ويرسله لـ `/ingest/file`
3. `_format_result()` يحقن النتائج في رسالة المستخدم
4. إزالة `store_document` من الأدوات (20 أداة بدل 21)

---

## 11. PDF مسحوب ضوئياً: pymupdf4llm يستخرج < 200 حرف
**المشكلة**: PDFs المبنية على صور (مستندات حكومية مسحوبة ضوئياً) — pymupdf4llm يستخرج نص قليل جداً.

**الحل**: `_pdf_to_vision()` — fallback تلقائي:
1. لو النص المستخرج < 200 حرف → يحول الصفحات لصور 200 DPI
2. يرسل كل صورة لـ Qwen3-VL vision (حد أقصى 5 صفحات)
3. يجمع النص من كل الصفحات ويكمل المعالجة

---

## 12. Item Quantity Double-Counting
**المشكلة**: المستخدم يرفع صورة ويقول "عندي من ٤ حبات" — الكمية تنحفظ 6 بدل 4.

**السبب**: المعالجة المزدوجة:
1. Image pipeline ينشئ Item (quantity=2 من vision)
2. Post-processing يستخرج quantity=4 من النص ويضيفه → 2+4=6

**الحل**: `upsert_item(quantity_mode="set")` — القيمة الافتراضية الآن SET (يستبدل) بدل ADD (يجمع).
`quantity_mode="add"` متاح للحالات اللي تحتاج إضافة فعلية.

---

## 13. LLM يولّد STATUS: PENDING_CONFIRMATION من عنده
**المشكلة**: الـ LLM في Open WebUI يولّد `STATUS: PENDING_CONFIRMATION` لما المستخدم يطلب إضافة تذكير — والمفروض التأكيد فقط للحذف.

**الحل**: إضافة قاعدتين في الفلتر:
1. "لا تسأل المستخدم هل تريد أضيف — أرسل الطلب مباشرة لأداة chat"
2. "لا تولّد STATUS: من عندك — هذه تأتي فقط من رد الأداة"

---

## 14. Extract Prompt: تواريخ تذكيرات سنوية خاطئة + أرقام مراجع مفقودة
**المشكلة**:
1. تذكير سنوي "30 يوم قبل" حدث في 2026-02-11 → التاريخ يطلع 2026-01-12 (ماضي) بدل 2027-01-12
2. أرقام المراجع (حجز، لوحة) ما تنحفظ في Knowledge nodes

**الحل**:
1. تعليمات صريحة: "تاريخ التذكير المتكرر = الحدث القادم المستقبلي"
2. مثالين few-shot جديدين: استخراج مستند رسمي + حساب تاريخ تذكير سنوي
3. تحسين Knowledge prompt: "استخرج كل الأرقام والمعرفات"
4. تحسين vision prompt لـ `official_document`: يطلب `reference_numbers` و `text_content`
