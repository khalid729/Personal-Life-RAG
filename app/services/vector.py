import logging
import uuid
from datetime import datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class VectorService:
    def __init__(self):
        self._model: SentenceTransformer | None = None
        self._client: AsyncQdrantClient | None = None

    async def start(self):
        logger.info("Loading BGE-M3 on %s...", settings.bge_device)
        self._model = SentenceTransformer(
            settings.bge_model_name,
            device=settings.bge_device,
        )
        logger.info("BGE-M3 loaded successfully")

        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        # Ensure collection exists
        collections = await self._client.get_collections()
        existing = [c.name for c in collections.collections]
        if settings.qdrant_collection not in existing:
            await self._client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=settings.bge_dimension,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s", settings.qdrant_collection)

        # Ensure payload index on file_hash for fast filtering
        try:
            await self._client.create_payload_index(
                collection_name=settings.qdrant_collection,
                field_name="file_hash",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # Index already exists

    async def stop(self):
        if self._client:
            await self._client.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    async def upsert_chunks(
        self,
        chunks: list[str],
        metadata_list: list[dict] | None = None,
    ) -> int:
        if not chunks:
            return 0

        vectors = self.embed(chunks)
        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            meta = metadata_list[i] if metadata_list and i < len(metadata_list) else {}
            payload = {
                "text": chunk,
                "created_at": datetime.utcnow().isoformat(),
                **meta,
            }
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload=payload,
                )
            )

        await self._client.upsert(
            collection_name=settings.qdrant_collection,
            points=points,
        )
        return len(points)

    async def delete_by_file_hash(self, file_hash: str) -> int:
        """Delete all Qdrant points with the given file_hash in their payload."""
        result = await self._client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=Filter(
                must=[FieldCondition(key="file_hash", match=MatchValue(value=file_hash))]
            ),
        )
        logger.info("Deleted chunks with file_hash=%s…: %s", file_hash[:12], result)
        return 1  # Qdrant delete doesn't return count, signal success

    async def search(
        self,
        query: str,
        limit: int = 5,
        source_type: str | None = None,
        entity_type: str | None = None,
        topic: str | None = None,
    ) -> list[dict]:
        query_vector = self.embed([query])[0]
        return await self.search_by_vector(
            query_vector, limit=limit, source_type=source_type,
            entity_type=entity_type, topic=topic,
        )

    async def search_by_vector(
        self,
        vector: list[float],
        limit: int = 5,
        source_type: str | None = None,
        entity_type: str | None = None,
        topic: str | None = None,
    ) -> list[dict]:
        """Search Qdrant using a pre-computed vector (skips embedding)."""
        filters = []
        if source_type:
            filters.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))
        if entity_type:
            filters.append(FieldCondition(key="entity_type", match=MatchValue(value=entity_type)))
        if topic:
            filters.append(FieldCondition(key="topic", match=MatchValue(value=topic)))

        query_filter = Filter(must=filters) if filters else None

        results = await self._client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

        return [
            {
                "text": point.payload.get("text", ""),
                "score": point.score,
                "metadata": {
                    k: v
                    for k, v in point.payload.items()
                    if k != "text"
                },
            }
            for point in results.points
        ]
