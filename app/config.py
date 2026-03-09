from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # vLLM
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_model: str = "Qwen/Qwen3-32B"

    # FalkorDB
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_graph_name: str = "personal_life"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "personal_life"

    # Redis (Memory)
    redis_host: str = "localhost"
    redis_port: int = 6380
    redis_db: int = 0

    # BGE-M3
    bge_model_name: str = "BAAI/bge-m3"
    bge_device: str = "cuda"
    bge_dimension: int = 1024

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8500

    # Memory
    working_memory_size: int = 4
    daily_summary_ttl_days: int = 7
    max_context_tokens: int = 15000

    # Chunking
    chunk_max_tokens: int = 1500
    chunk_overlap_tokens: int = 100

    # File Processing
    file_storage_path: str = "data/files"
    max_file_size_mb: int = 50

    # WhisperX (legacy — replaced by Deepgram)
    whisperx_model: str = "large-v3"
    whisperx_compute_type: str = "float16"
    whisperx_batch_size: int = 8
    whisperx_language: str = "ar"
    whisperx_beam_size: int = 5

    # Deepgram STT (Nova-3 Arabic)
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "ar-SA"

    # Agentic RAG
    agentic_max_retries: int = 1
    self_rag_threshold: float = 0.3

    # Conversation (Phase 4)
    daily_summary_interval: int = 10
    core_memory_interval: int = 20

    # Telegram (Phase 5)
    telegram_bot_token: str = ""
    tg_chat_id: str = ""

    # MCP (Phase 5)
    mcp_port: int = 8600

    # Claude API
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    use_claude_for_chat: bool = False
    use_claude_for_vision: bool = False
    use_claude_for_extraction: bool = False  # Route extraction/enrichment/translation to Claude instead of vLLM

    # Timezone
    timezone_offset_hours: int = 3  # Asia/Riyadh UTC+3

    # Prayer Times
    prayer_city: str = "Dammam"
    prayer_country: str = "Saudi Arabia"
    prayer_method: int = 4  # Umm Al-Qura
    prayer_offset_minutes: int = 20  # "بعد صلاة X" = prayer time + offset
    nag_interval_minutes: int = 30  # how often persistent reminders re-fire

    # Home Assistant (Phase 26)
    ha_enabled: bool = False
    ha_url: str = ""           # http://192.168.68.72:8123
    ha_token: str = ""         # Long-Lived Access Token
    ha_cache_ttl: int = 30     # entity state cache seconds

    # Location-Based Reminders (Phase 24)
    location_enabled: bool = False
    location_default_radius: int = 150      # meters
    location_cooldown_minutes: int = 10     # skip duplicate zone fires
    nominatim_user_agent: str = "PersonalRAG/1.0"
    nominatim_cache_ttl_days: int = 7

    # Proactive System (Phase 6)
    proactive_enabled: bool = True
    proactive_morning_hour: int = 7
    proactive_noon_hour: int = 13
    proactive_evening_hour: int = 21
    proactive_reminder_check_minutes: int = 1
    proactive_alert_check_hours: int = 6
    proactive_stalled_days: int = 14
    proactive_old_debt_days: int = 30

    # Entity Resolution (Phase 8)
    entity_resolution_enabled: bool = True
    entity_resolution_person_threshold: float = 0.85
    entity_resolution_default_threshold: float = 0.80
    graph_max_hops: int = 3

    # Inventory (Phase 9)
    inventory_unused_days: int = 90
    inventory_report_top_n: int = 10

    # Productivity (Phase 10)
    productivity_enabled: bool = True
    energy_peak_hours: str = "7-12"
    energy_low_hours: str = "14-16"
    work_day_start: int = 7
    work_day_end: int = 22
    default_energy_profile: str = "normal"  # "normal", "tired", "energized"
    pomodoro_default_minutes: int = 25
    time_block_slot_minutes: int = 30
    sprint_default_weeks: int = 2

    # Multi-Tenancy (Phase 23)
    multi_tenant_enabled: bool = False
    default_user_id: str = "khalid"
    admin_api_key: str = ""
    users_file: str = "data/users.json"

    # Backup (Phase 11)
    backup_enabled: bool = True
    backup_hour: int = 3  # 3 AM local
    backup_retention_days: int = 30
    backup_dir: str = "data/backups"

    # Arabic NER (Phase 11)
    arabic_ner_enabled: bool = True
    arabic_ner_model: str = "CAMeL-Lab/bert-base-arabic-camelbert-msa-ner"

    # Auto-extraction from conversational messages
    auto_extract_enabled: bool = False  # disabled: saves contradictory data on corrections

    # Conversation Summarization (Phase 11)
    conversation_compress_threshold: int = 10
    conversation_compress_keep_recent: int = 4

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
