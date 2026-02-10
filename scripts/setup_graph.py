#!/usr/bin/env python3
"""Initialize FalkorDB schema: indexes, constraints, and seed data."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging

from falkordb.asyncio import FalkorDB
from redis.asyncio import BlockingConnectionPool

from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# FalkorDB uses GRAPH.CONSTRAINT CREATE for unique constraints
# and CREATE INDEX for indexes (Cypher-based)

INDEXES = [
    "CREATE INDEX FOR (p:Person) ON (p.name)",
    "CREATE INDEX FOR (p:Project) ON (p.name)",
    "CREATE INDEX FOR (p:Project) ON (p.status)",
    "CREATE INDEX FOR (e:Expense) ON (e.created_at)",
    "CREATE INDEX FOR (e:Expense) ON (e.category)",
    "CREATE INDEX FOR (d:Debt) ON (d.status)",
    "CREATE INDEX FOR (d:Debt) ON (d.direction)",
    "CREATE INDEX FOR (r:Reminder) ON (r.due_date)",
    "CREATE INDEX FOR (r:Reminder) ON (r.status)",
    "CREATE INDEX FOR (r:Reminder) ON (r.reminder_type)",
    "CREATE INDEX FOR (t:Task) ON (t.status)",
    "CREATE INDEX FOR (t:Task) ON (t.due_date)",
    "CREATE INDEX FOR (f:File) ON (f.file_hash)",
    "CREATE INDEX FOR (t:Topic) ON (t.name)",
    "CREATE INDEX FOR (t:Tag) ON (t.name)",
    "CREATE INDEX FOR (c:Company) ON (c.name)",
    "CREATE INDEX FOR (i:Idea) ON (i.title)",
    "CREATE INDEX FOR (k:Knowledge) ON (k.title)",
]

# FalkorDB unique constraints use a different syntax than Neo4j
UNIQUE_CONSTRAINTS = [
    ("Person", "name"),
    ("Project", "name"),
    ("Topic", "name"),
    ("Tag", "name"),
    ("Company", "name"),
    ("File", "file_hash"),
]

DEFAULT_TOPICS = [
    "Finance",
    "Projects",
    "Ideas",
    "Home",
    "Health",
    "Work",
    "Learning",
    "Relationships",
    "Daily",
]


async def main():
    pool = BlockingConnectionPool(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        max_connections=4,
        timeout=None,
        decode_responses=True,
    )
    db = FalkorDB(connection_pool=pool)
    graph = db.select_graph(settings.falkordb_graph_name)

    # Create indexes
    logger.info("Creating indexes...")
    for idx in INDEXES:
        try:
            await graph.query(idx)
            logger.info("  OK: %s", idx[:60])
        except Exception as e:
            if "already indexed" in str(e).lower() or "already exists" in str(e).lower():
                logger.info("  SKIP (exists): %s", idx[:60])
            else:
                logger.warning("  FAIL: %s — %s", idx[:60], e)

    # Create unique constraints
    logger.info("Creating unique constraints...")
    for label, prop in UNIQUE_CONSTRAINTS:
        try:
            # FalkorDB constraint syntax
            cmd = f"GRAPH.CONSTRAINT CREATE {settings.falkordb_graph_name} UNIQUE NODE {label} PROPERTIES 1 {prop}"
            # Use the underlying Redis connection for raw commands
            redis_conn = await pool.get_connection()
            await redis_conn.send_command(*cmd.split())
            resp = await redis_conn.read_response()
            await pool.release(redis_conn)
            logger.info("  OK: UNIQUE %s.%s", label, prop)
        except Exception as e:
            if "already" in str(e).lower() or "exists" in str(e).lower():
                logger.info("  SKIP (exists): UNIQUE %s.%s", label, prop)
            else:
                logger.warning("  FAIL: UNIQUE %s.%s — %s", label, prop, e)

    # Seed default topics
    logger.info("Seeding default topics...")
    from datetime import datetime

    for topic_name in DEFAULT_TOPICS:
        try:
            await graph.query(
                "MERGE (t:Topic {name: $name}) ON CREATE SET t.created_at = $now",
                params={"name": topic_name, "now": datetime.utcnow().isoformat()},
            )
            logger.info("  OK: Topic '%s'", topic_name)
        except Exception as e:
            logger.warning("  FAIL: Topic '%s' — %s", topic_name, e)

    await pool.aclose()
    logger.info("FalkorDB schema setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
