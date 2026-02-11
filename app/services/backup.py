"""Backup service — dump and restore FalkorDB, Qdrant, and Redis data."""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import get_settings
from app.services.graph import GraphService
from app.services.memory import MemoryService
from app.services.vector import VectorService

logger = logging.getLogger(__name__)
settings = get_settings()


def _now_local() -> datetime:
    tz = timezone(timedelta(hours=settings.timezone_offset_hours))
    return datetime.now(tz)


class BackupService:
    def __init__(
        self,
        graph: GraphService,
        vector: VectorService,
        memory: MemoryService,
    ):
        self.graph = graph
        self.vector = vector
        self.memory = memory
        self.backup_dir = Path(settings.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(self) -> dict:
        timestamp = _now_local().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / timestamp
        backup_path.mkdir(parents=True, exist_ok=True)

        sizes = {}
        try:
            sizes["graph"] = await self._backup_graph(backup_path)
        except Exception as e:
            logger.error("Graph backup failed: %s", e)
            sizes["graph"] = 0

        try:
            sizes["vector"] = await self._backup_qdrant(backup_path)
        except Exception as e:
            logger.error("Qdrant backup failed: %s", e)
            sizes["vector"] = 0

        try:
            sizes["redis"] = await self._backup_redis(backup_path)
        except Exception as e:
            logger.error("Redis backup failed: %s", e)
            sizes["redis"] = 0

        logger.info("Backup created: %s (graph=%d, vector=%d, redis=%d bytes)",
                     timestamp, sizes["graph"], sizes["vector"], sizes["redis"])
        return {"timestamp": timestamp, "path": str(backup_path), "sizes": sizes}

    async def list_backups(self) -> list[dict]:
        backups = []
        if not self.backup_dir.exists():
            return backups
        for entry in sorted(self.backup_dir.iterdir(), reverse=True):
            if entry.is_dir() and len(entry.name) == 15:  # YYYYMMDD_HHMMSS
                total_size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                files = [f.name for f in entry.iterdir() if f.is_file()]
                backups.append({
                    "timestamp": entry.name,
                    "size_bytes": total_size,
                    "files": files,
                })
        return backups

    async def restore_backup(self, timestamp: str) -> dict:
        backup_path = self.backup_dir / timestamp
        if not backup_path.exists():
            return {"error": f"Backup {timestamp} not found"}

        restored = {}

        graph_file = backup_path / "graph.json"
        if graph_file.exists():
            try:
                restored["graph"] = await self._restore_graph(graph_file)
            except Exception as e:
                logger.error("Graph restore failed: %s", e)
                restored["graph"] = {"error": str(e)}

        vector_file = backup_path / "vector.json"
        if vector_file.exists():
            try:
                restored["vector"] = await self._restore_qdrant(vector_file)
            except Exception as e:
                logger.error("Qdrant restore failed: %s", e)
                restored["vector"] = {"error": str(e)}

        redis_file = backup_path / "redis.json"
        if redis_file.exists():
            try:
                restored["redis"] = await self._restore_redis(redis_file)
            except Exception as e:
                logger.error("Redis restore failed: %s", e)
                restored["redis"] = {"error": str(e)}

        logger.info("Backup restored: %s", timestamp)
        return {"timestamp": timestamp, "restored": restored}

    async def cleanup_old_backups(self) -> int:
        cutoff = _now_local() - timedelta(days=settings.backup_retention_days)
        cutoff_str = cutoff.strftime("%Y%m%d_%H%M%S")
        removed = 0
        if not self.backup_dir.exists():
            return 0
        for entry in self.backup_dir.iterdir():
            if entry.is_dir() and len(entry.name) == 15 and entry.name < cutoff_str:
                shutil.rmtree(entry)
                removed += 1
                logger.info("Removed old backup: %s", entry.name)
        return removed

    # --- Graph backup ---

    async def _backup_graph(self, backup_path: Path) -> int:
        nodes = []
        rows = await self.graph.query(
            "MATCH (n) RETURN n, labels(n) AS lbls"
        )
        for row in rows:
            node = row[0]
            labels = row[1] if len(row) > 1 else []
            props = node.properties if hasattr(node, "properties") else {}
            nodes.append({"labels": labels, "properties": dict(props)})

        edges = []
        rows = await self.graph.query(
            "MATCH (a)-[r]->(b) RETURN a.name, labels(a), type(r), properties(r), b.name, labels(b)"
        )
        for row in rows:
            edges.append({
                "source_name": row[0],
                "source_labels": row[1],
                "rel_type": row[2],
                "rel_properties": row[3] if row[3] else {},
                "target_name": row[4],
                "target_labels": row[5],
            })

        data = {"nodes": nodes, "edges": edges}
        out_file = backup_path / "graph.json"
        out_file.write_text(json.dumps(data, ensure_ascii=False, default=str))
        return out_file.stat().st_size

    async def _restore_graph(self, graph_file: Path) -> dict:
        data = json.loads(graph_file.read_text())
        node_count = 0
        for node in data.get("nodes", []):
            labels = node.get("labels", [])
            props = node.get("properties", {})
            if not labels or not props:
                continue
            label = labels[0] if isinstance(labels, list) else labels
            # Determine the key field for MERGE
            key_field = "name"
            if "description" in props and "name" not in props:
                key_field = "description"
            key_val = props.get(key_field)
            if not key_val:
                continue
            set_parts = []
            params = {"key_val": key_val}
            for k, v in props.items():
                if k == key_field:
                    continue
                safe_k = k.replace(" ", "_").replace("-", "_")
                params[f"p_{safe_k}"] = v
                set_parts.append(f"n.{k} = $p_{safe_k}")
            set_clause = ", ".join(set_parts)
            if set_clause:
                set_clause = f"SET {set_clause}"
            q = f"MERGE (n:{label} {{{key_field}: $key_val}}) {set_clause}"
            try:
                await self.graph.query(q, params)
                node_count += 1
            except Exception as e:
                logger.debug("Restore node failed: %s", e)

        edge_count = 0
        for edge in data.get("edges", []):
            src_label = edge["source_labels"][0] if edge.get("source_labels") else "Entity"
            tgt_label = edge["target_labels"][0] if edge.get("target_labels") else "Entity"
            rel_type = edge.get("rel_type", "RELATED_TO")
            src_name = edge.get("source_name")
            tgt_name = edge.get("target_name")
            if not src_name or not tgt_name:
                continue
            rel_props = edge.get("rel_properties", {})
            params = {"src": src_name, "tgt": tgt_name}
            set_parts = []
            for k, v in rel_props.items():
                safe_k = k.replace(" ", "_").replace("-", "_")
                params[f"r_{safe_k}"] = v
                set_parts.append(f"r.{k} = $r_{safe_k}")
            set_clause = ""
            if set_parts:
                set_clause = " SET " + ", ".join(set_parts)
            q = (
                f"MATCH (a:{src_label} {{name: $src}}) "
                f"MATCH (b:{tgt_label} {{name: $tgt}}) "
                f"MERGE (a)-[r:{rel_type}]->(b){set_clause}"
            )
            try:
                await self.graph.query(q, params)
                edge_count += 1
            except Exception as e:
                logger.debug("Restore edge failed: %s", e)

        return {"nodes": node_count, "edges": edge_count}

    # --- Qdrant backup ---

    async def _backup_qdrant(self, backup_path: Path) -> int:
        from qdrant_client.models import ScrollRequest

        all_points = []
        offset = None
        batch_size = 100
        while True:
            result = await self.vector._client.scroll(
                collection_name=settings.qdrant_collection,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            points, next_offset = result
            for p in points:
                all_points.append({
                    "id": str(p.id),
                    "vector": p.vector,
                    "payload": p.payload,
                })
            if next_offset is None or not points:
                break
            offset = next_offset

        out_file = backup_path / "vector.json"
        out_file.write_text(json.dumps(all_points, ensure_ascii=False, default=str))
        logger.info("Qdrant backup: %d points", len(all_points))
        return out_file.stat().st_size

    async def _restore_qdrant(self, vector_file: Path) -> dict:
        from qdrant_client.models import PointStruct

        data = json.loads(vector_file.read_text())
        batch_size = 100
        total = 0
        for i in range(0, len(data), batch_size):
            batch = data[i : i + batch_size]
            points = []
            for p in batch:
                points.append(
                    PointStruct(
                        id=p["id"],
                        vector=p["vector"],
                        payload=p.get("payload", {}),
                    )
                )
            await self.vector._client.upsert(
                collection_name=settings.qdrant_collection,
                points=points,
            )
            total += len(points)
        return {"points_restored": total}

    # --- Redis backup ---

    async def _backup_redis(self, backup_path: Path) -> int:
        redis = self.memory._redis
        keys_data = {}
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, count=100)
            for key in keys:
                key_type = await redis.type(key)
                if key_type == "string":
                    val = await redis.get(key)
                    keys_data[key] = {"type": "string", "value": val}
                elif key_type == "list":
                    vals = await redis.lrange(key, 0, -1)
                    keys_data[key] = {"type": "list", "value": vals}
                elif key_type == "hash":
                    vals = await redis.hgetall(key)
                    keys_data[key] = {"type": "hash", "value": vals}
                elif key_type == "set":
                    vals = list(await redis.smembers(key))
                    keys_data[key] = {"type": "set", "value": vals}
                ttl = await redis.ttl(key)
                if key in keys_data and ttl > 0:
                    keys_data[key]["ttl"] = ttl
            if cursor == 0:
                break

        out_file = backup_path / "redis.json"
        out_file.write_text(json.dumps(keys_data, ensure_ascii=False, default=str))
        logger.info("Redis backup: %d keys", len(keys_data))
        return out_file.stat().st_size

    async def _restore_redis(self, redis_file: Path) -> dict:
        redis = self.memory._redis
        data = json.loads(redis_file.read_text())
        restored = 0
        for key, info in data.items():
            key_type = info["type"]
            value = info["value"]
            ttl = info.get("ttl")
            try:
                if key_type == "string":
                    await redis.set(key, value)
                elif key_type == "list":
                    await redis.delete(key)
                    if value:
                        await redis.rpush(key, *value)
                elif key_type == "hash":
                    await redis.delete(key)
                    if value:
                        await redis.hset(key, mapping=value)
                elif key_type == "set":
                    await redis.delete(key)
                    if value:
                        await redis.sadd(key, *value)
                if ttl and ttl > 0:
                    await redis.expire(key, ttl)
                restored += 1
            except Exception as e:
                logger.debug("Restore key '%s' failed: %s", key, e)
        return {"keys_restored": restored}
