# Phase 26: Home Assistant Integration

## Context

دمج Home Assistant الشغال على `192.168.68.72:8123` مع Personal Life RAG.
HA فيه 637 entity (69 نور، 63 سويتش، 42 ميديا بلير، 2 cover، 150 سنسور، 9 أتمتة).
الأسماء العربية موجودة كـ `friendly_name` في HA (الثريا، غرفه نومي، المطبخ...).

**الهدف**: تحكم بالأجهزة من الشات + مراقبة من الداشبورد + أتمتة مؤقتة عبر التذكيرات + إشعارات من HA.

## Multi-Tenancy (خالد + روابي)

كلا الحسابين يتحكمون بنفس HA (`192.168.68.72:8123`). HA واحد، توكن واحد.

| Feature | Per-User? | Details |
|---------|-----------|---------|
| التحكم بالأجهزة | مشترك | كلهم يتحكمون بنفس الأجهزة |
| أسماء مخصصة | **لكل مستخدم** | روابي تسمي "نور غرفتي" غير خالد |
| تذكير + HA | **لكل مستخدم** | كل واحد تذكيراته في جرافه الخاص |
| إشعارات webhook | **لكل مستخدم** | كل واحد يوصله على بوته |
| كاش الأجهزة | مشترك | نفس الأجهزة لأن نفس HA |

**تقنياً**: HA URL/Token في `.env` (مشترك). أسماء مخصصة في Redis مفصولة بـ `redis_prefix` (خالد: `ha:names:` / روابي: `ha:names:rawabi:`).

## How It Works

### طريقة التكامل
- **REST API**: المشروع يتصل بـ HA عبر `http://192.168.68.72:8123/api/` باستخدام Long-Lived Access Token
- **لا حاجة لـ SSH**: كل شي عبر HTTP
- **اكتشاف تلقائي**: `GET /api/states` يرجع كل الأجهزة مع `friendly_name` العربي — أي جهاز جديد يظهر تلقائياً (كاش 30 ثانية)
- **مطابقة الأسماء**: Claude يطابق كلام المستخدم بالعربي مع `friendly_name` من HA مباشرة
- **متعدد المستخدمين**: خالد وروابي يتحكمون من حساباتهم — كل واحد من بوت تلقرام الخاص فيه

### الأتمتة المؤقتة (عبر التذكيرات)
"بعد ساعة طفي نور الصالة" → `create_reminder` مع `ha_action` → لما يحين الوقت → `proactive` يطلق التذكير → ينفذ أمر HA تلقائياً → يرسل تأكيد تلقرام.

### الأتمتة الدائمة
نوعين:
1. **تذكير متكرر + أمر HA**: "كل يوم الساعة 6 شغل نور المطبخ" → تذكير يومي مع `ha_action`
2. **HA → RAG webhook**: أتمتة في HA ترسل webhook لـ RAG → RAG يرسل إشعار تلقرام

---

## Implementation Steps

### Step 1: Config (`app/config.py` + `.env`)

Add to `Settings` class:
```python
# Home Assistant (Phase 26)
ha_enabled: bool = False
ha_url: str = ""           # http://192.168.68.72:8123
ha_token: str = ""         # Long-Lived Access Token
ha_cache_ttl: int = 30     # entity state cache seconds
```

Add to `.env`:
```
HA_ENABLED=true
HA_URL=http://192.168.68.72:8123
HA_TOKEN=eyJhbGci...
```

---

### Step 2: HA Service (`app/services/homeassistant.py`) — New File

Async httpx client with Redis caching. Pattern: follows `LocationService`.

**Key Methods:**

| Method | HA API | Purpose |
|--------|--------|---------|
| `get_states(domain_filter?)` | `GET /api/states` | All entities (cached 30s in Redis) |
| `get_state(entity_id)` | `GET /api/states/{id}` | Single entity |
| `call_service(domain, service, data)` | `POST /api/services/{domain}/{service}` | Turn on/off/toggle/set_temp |
| `resolve_entity(name)` | (internal) | Arabic name → entity_id matching |
| `set_entity_name(entity_id, arabic)` | (Redis) | Custom Arabic nickname mapping |
| `get_entity_names()` | (Redis) | List all custom nicknames |

**Entity Resolution Flow:**
```
1. Direct entity_id check ("light.mb" → return as-is)
2. Custom Arabic nickname (Redis hash ha:names:{prefix})
3. Fuzzy match on HA friendly_name (from cached states)
   - Exact match first, then substring (contains)
```

**State Caching:**
- Redis key: `ha:states:{user_prefix}` — TTL 30s
- New devices appear within 30s automatically
- `call_service` invalidates cache immediately

---

### Step 3: HA Router (`app/routers/homeassistant.py`) — New File

Dashboard REST endpoints:

```
GET  /ha/states                      → all states (optional domain filter)
GET  /ha/states/{entity_id}          → single entity
POST /ha/services/{domain}/{service} → call service
GET  /ha/names                       → custom Arabic name mappings
POST /ha/names                       → set mapping {entity_id, arabic_name}
DELETE /ha/names/{name}              → delete mapping
POST /ha/webhook                     → receive HA automation events → Telegram notify
```

---

### Step 4: Chat Tools (3 new tools in `tool_calling.py`)

**Tool 1: `control_device`** — تحكم بجهاز (شغل/طفي/toggle/حرارة/ستائر...)
```
params: device (str), action (enum: turn_on/turn_off/toggle/set_temperature/...), data (optional dict)
```
Handler: resolve entity → call_service → return status

**Tool 2: `query_device`** — استعلام عن حالة جهاز أو قائمة الأجهزة
```
params: device (optional str), domain (optional enum: light/switch/climate/...)
```
Handler: resolve entity → get_state (or get_states for list)

**Tool 3: `manage_ha_names`** — إدارة أسماء عربية مخصصة
```
params: action (list/set/delete), arabic_name, entity_id
```

---

### Step 5: Reminder + HA Action Integration

**Graph Schema Change:** Add optional properties to Reminder nodes:
```
ha_entity_id: str     (e.g., "light.ktn_out")
ha_action: str        (e.g., "turn_off")
ha_action_data: str   (JSON string, e.g., '{"temperature": 22}')
```

**`create_reminder` tool change:** Add optional params:
```python
ha_entity_id: str | None = None    # جهاز HA مرتبط
ha_action: str | None = None       # الإجراء (turn_on/turn_off/...)
ha_action_data: str | None = None  # بيانات إضافية (JSON)
```

**Proactive firing change** (`telegram_bot.py` `job_check_reminders`):
When a due reminder has `ha_entity_id` + `ha_action`:
1. Call `POST /ha/services/{domain}/{action}` with the entity
2. Include HA result in the notification message: "✅ تم تنفيذ: طفي نور المطبخ"

---

### Step 6: Tool Prompt (`app/prompts/tool_system.py`)

Add instructions (after line 102):
```
- لو {user_name} يبي يتحكم بجهاز ذكي (نور، مكيف، ستائر، سبيكر)، استخدم control_device.
  مثال: "شغل المكيف" → control_device(device="المكيف", action="turn_on")
  مثال: "حط المكيف على ٢٢" → control_device(device="المكيف", action="set_temperature", data={"temperature": 22})
- لو يسأل "وش حالة النور" أو "وش الأجهزة المتاحة"، استخدم query_device.
- لو يبي يسمي جهاز باسم عربي مخصص، استخدم manage_ha_names مع action=set.
- لو يبي يتحكم بجهاز بوقت ("بعد ساعة طفي النور")، أنشئ تذكير مع ha_entity_id + ha_action.
- ترجم الأوامر: شغل=turn_on، أطفي/طفي=turn_off، افتح=open_cover، أقفل=lock، toggle=بدّل.
```

---

### Step 7: Main + Dependencies (`app/main.py`)

```python
from app.services.homeassistant import HomeAssistantService
from app.routers import homeassistant as ha_router

# In lifespan (after location_svc):
ha_svc = HomeAssistantService(memory._redis)
await ha_svc.start()
app.state.ha = ha_svc

# ToolCallingService gets ha:
tool_calling = ToolCallingService(..., ha=ha_svc)

# Register router:
app.include_router(ha_router.router)

# Shutdown:
await ha_svc.stop()
```

`ToolCallingService.__init__` change: add `ha=None` param, register 3 handlers.

---

### Step 8: Dashboard Page (`dashboard/src/pages/HomeAssistantPage.tsx`)

**Layout:**
- Connection status badge (green/red)
- Domain filter tabs: الكل | أنوار | سويتشات | ميديا | ستائر | سنسورات
- Device cards grid (grouped by room/area if available, else by domain)

**Device Card:**
| Domain | Display | Controls |
|--------|---------|----------|
| light | اسم + حالة (on/off) | زر toggle |
| switch | اسم + حالة | زر toggle |
| climate | اسم + حرارة + وضع | +/- حرارة |
| cover | اسم + حالة (open/closed) | أزرار open/close |
| media_player | اسم + حالة (playing/off) | play/pause |
| sensor | اسم + قيمة + وحدة | (قراءة فقط) |

**Arabic Name Manager:** Dialog لربط أسماء مخصصة بالأجهزة.

**Sidebar:** إضافة "المنزل الذكي" تحت "الموقع" مع أيقونة Home.

---

### Step 9: HA Webhook (HA → RAG)

**HA Automation YAML** (المستخدم يضيفها في HA):
```yaml
rest_command:
  rag_ha_event:
    url: "http://192.168.68.62:8500/ha/webhook"
    method: POST
    headers:
      X-API-Key: "<api-key>"
      Content-Type: "application/json"
    payload: '{"event_type":"{{ event }}","entity_id":"{{ entity_id }}","new_state":"{{ new_state }}"}'
```

**Webhook Processing:**
1. Receive event from HA
2. Resolve entity_id → Arabic friendly_name
3. Format message: `"🏠 {event}: {name} → {state}"`
4. Send Telegram notification

---

## Files Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `app/config.py` | Edit | +4 |
| `.env` | Edit | +3 |
| `app/services/homeassistant.py` | **New** | ~200 |
| `app/routers/homeassistant.py` | **New** | ~130 |
| `app/services/tool_calling.py` | Edit | ~130 (3 defs + 3 handlers + init + reminder change) |
| `app/prompts/tool_system.py` | Edit | +5 |
| `app/main.py` | Edit | +8 |
| `app/integrations/telegram_bot.py` | Edit | ~15 (HA action on reminder fire) |
| `dashboard/src/pages/HomeAssistantPage.tsx` | **New** | ~250 |
| `dashboard/src/components/AppSidebar.tsx` | Edit | +1 |
| `app/routers/__init__.py` (if exists) | Edit | +1 |

---

## Verification

1. **Import check**: `python -c "from app.services.homeassistant import HomeAssistantService; print('OK')"`
2. **API test**: `curl http://localhost:8500/ha/states -H "X-API-Key: <key>"` → device list
3. **Control test**: `curl -X POST http://localhost:8500/ha/services/light/toggle -H "X-API-Key: <key>" -d '{"entity_id": "light.mb"}'`
4. **Chat test**: "شغل نور الصالة" via `/chat/v2` → `control_device` called → HA executes
5. **Query test**: "وش حالة الأنوار" → `query_device(domain="light")` → states returned
6. **Timed control**: "بعد ساعة طفي نور المطبخ" → reminder created with `ha_action` → fires in 1hr → HA executes
7. **Dashboard**: `/homeassistant` page shows devices with toggle controls
8. **Restart**: `sudo systemctl restart rag-server`
