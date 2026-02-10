#!/usr/bin/env python3
"""Test all services individually."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def test_docker_containers():
    """Check that Docker containers are healthy."""
    import subprocess

    logger.info("=== Testing Docker Containers ===")
    containers = ["falkordb-personal", "qdrant-personal", "redis-personal"]
    all_ok = True
    for name in containers:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
        )
        running = result.stdout.strip() == "true"
        status = "✓ running" if running else "✗ NOT running"
        logger.info("  %s: %s", name, status)
        if not running:
            all_ok = False
    return all_ok


async def test_vllm():
    """Test vLLM connection."""
    import httpx

    logger.info("=== Testing vLLM ===")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("http://localhost:8000/v1/models")
            resp.raise_for_status()
            models = resp.json()["data"]
            logger.info("  ✓ vLLM connected, models: %s", [m["id"] for m in models])
            return True
    except Exception as e:
        logger.error("  ✗ vLLM failed: %s", e)
        return False


async def test_falkordb():
    """Test FalkorDB connection."""
    from falkordb.asyncio import FalkorDB
    from redis.asyncio import BlockingConnectionPool
    from app.config import get_settings

    settings = get_settings()
    logger.info("=== Testing FalkorDB ===")
    try:
        pool = BlockingConnectionPool(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            max_connections=2,
            timeout=None,
            decode_responses=True,
        )
        db = FalkorDB(connection_pool=pool)
        graph = db.select_graph(settings.falkordb_graph_name)
        result = await graph.query("RETURN 1 as test")
        assert result.result_set[0][0] == 1
        await pool.aclose()
        logger.info("  ✓ FalkorDB connected and responding")
        return True
    except Exception as e:
        logger.error("  ✗ FalkorDB failed: %s", e)
        return False


async def test_qdrant():
    """Test Qdrant connection."""
    from qdrant_client import AsyncQdrantClient
    from app.config import get_settings

    settings = get_settings()
    logger.info("=== Testing Qdrant ===")
    try:
        client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        collections = await client.get_collections()
        logger.info("  ✓ Qdrant connected, collections: %s", [c.name for c in collections.collections])
        await client.close()
        return True
    except Exception as e:
        logger.error("  ✗ Qdrant failed: %s", e)
        return False


async def test_redis():
    """Test Redis memory connection."""
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    logger.info("=== Testing Redis ===")
    try:
        r = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
        )
        pong = await r.ping()
        assert pong is True
        await r.aclose()
        logger.info("  ✓ Redis connected and responding")
        return True
    except Exception as e:
        logger.error("  ✗ Redis failed: %s", e)
        return False


async def test_bge_m3():
    """Test BGE-M3 embedding model loading."""
    logger.info("=== Testing BGE-M3 ===")
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("BAAI/bge-m3", device="cuda")
        embeddings = model.encode(["test sentence"], normalize_embeddings=True)
        assert embeddings.shape == (1, 1024)
        logger.info("  ✓ BGE-M3 loaded on GPU, dimension: %d", embeddings.shape[1])
        del model
        return True
    except Exception as e:
        logger.error("  ✗ BGE-M3 failed: %s", e)
        return False


async def main():
    logger.info("Personal Life RAG — Service Tests\n")

    results = {}
    results["docker"] = await test_docker_containers()
    results["vllm"] = await test_vllm()
    results["falkordb"] = await test_falkordb()
    results["qdrant"] = await test_qdrant()
    results["redis"] = await test_redis()
    results["bge_m3"] = await test_bge_m3()

    logger.info("\n=== Summary ===")
    all_passed = True
    for name, ok in results.items():
        status = "✓ PASS" if ok else "✗ FAIL"
        logger.info("  %s: %s", name, status)
        if not ok:
            all_passed = False

    if all_passed:
        logger.info("\nAll tests passed! Ready to start the API.")
    else:
        logger.error("\nSome tests failed. Fix the issues above before starting.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
