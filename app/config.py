from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # vLLM
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_model: str = "Qwen/Qwen3-VL-32B-Instruct"

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
    working_memory_size: int = 5
    daily_summary_ttl_days: int = 7
    max_context_tokens: int = 15000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
