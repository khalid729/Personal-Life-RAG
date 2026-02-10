# المرحلة 1: الأساس + Contextual Retrieval

## Context
بناء البنية التحتية الأساسية لنظام إدارة الحياة الشخصية (Personal Life RAG). المرحلة تشمل: تشغيل قواعد البيانات، بناء الخدمات الأساسية، وتنفيذ Contextual Retrieval pipeline مع FastAPI API.

**المجلد**: `/home/khalid/Projects/Personal_Rag/`

**البنية الموجودة والشغالة** (ما نلمسها):
- vLLM على port 8000 (Qwen3-VL-32B)
- Open WebUI على port 3000
- BGE-M3 محمّل في `/home/khalid/.cache/huggingface/hub/models--BAAI--bge-m3/`
- خدمات ISE2026 (Neo4j, ChromaDB) شغالة على بورتات مختلفة

---

## هيكل المشروع

```
/home/khalid/Projects/Personal_Rag/
├── personal-life-rag-plan.md        # (موجود)
├── .env                             # Environment variables
├── requirements.txt
├── docker-compose.yml               # FalkorDB + Qdrant + Redis
├── app/
│   ├── __init__.py
│   ├── config.py                    # Settings singleton
│   ├── main.py                      # FastAPI entry point (port 8500)
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py               # Pydantic models لكل الكيانات
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm.py                   # vLLM async client (ترجمة، تصنيف، استخراج)
│   │   ├── graph.py                 # FalkorDB client + Cypher queries
│   │   ├── vector.py                # Qdrant + BGE-M3 embeddings
│   │   ├── memory.py                # Redis 3-layer memory
│   │   └── retrieval.py             # Contextual Retrieval + Smart Router
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py                  # POST /chat/
│   │   ├── ingest.py                # POST /ingest/text
│   │   └── search.py                # POST /search/
│   └── prompts/
│       ├── __init__.py
│       ├── translate.py             # Arabic <-> English
│       ├── classify.py              # تصنيف نوع السؤال
│       └── extract.py               # استخراج حقائق JSON
├── scripts/
│   ├── setup_graph.py               # تهيئة FalkorDB schema
│   ├── start.sh                     # تشغيل API
│   └── test_services.py             # اختبار الخدمات
└── data/                            # Docker volumes
    ├── falkordb/
    ├── qdrant/
    └── redis/
```

---

## خطوات التنفيذ بالترتيب

### الخطوة 1: البنية التحتية (Docker + venv + dependencies)
### الخطوة 2: Config + Pydantic Schemas
### الخطوة 3: Prompt Templates
### الخطوة 4: Core Services (LLM, Graph, Vector, Memory)
### الخطوة 5: Retrieval Pipeline + Smart Router
### الخطوة 6: API Routers + Main App
### الخطوة 7: FalkorDB Schema Setup
### الخطوة 8: اختبار وتشغيل
