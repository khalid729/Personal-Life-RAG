import logging
import uuid
from datetime import datetime

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
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

    async def search(
        self,
        query: str,
        limit: int = 5,
        source_type: str | None = None,
        entity_type: str | None = None,
        topic: str | None = None,
    ) -> list[dict]:
        query_vector = self.embed([query])[0]

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
            query=query_vector,
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
