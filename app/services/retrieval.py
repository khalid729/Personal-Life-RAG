import asyncio
import logging

import tiktoken

from app.config import get_settings
from app.services.graph import GraphService
from app.services.llm import LLMService
from app.services.memory import MemoryService
from app.services.vector import VectorService

settings = get_settings()

logger = logging.getLogger(__name__)

# Tokenizer for context budget
_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _is_mostly_english(text: str, sample_size: int = 500) -> bool:
    """Check if text is mostly English/ASCII (skip translation for English docs)."""
    sample = text[:sample_size]
    if not sample:
        return True
    arabic_count = sum(1 for c in sample if '\u0600' <= c <= '\u06FF')
    return arabic_count / len(sample) < 0.1


def chunk_text(
    text: str,
    max_tokens: int = settings.chunk_max_tokens,
    overlap_tokens: int = settings.chunk_overlap_tokens,
) -> list[str]:
    """Split text into chunks of ~max_tokens with overlap."""
    words = text.split()
    chunks = []
    current: list[str] = []
    current_tokens = 0

    for word in words:
        word_tokens = count_tokens(word + " ")
        if current_tokens + word_tokens > max_tokens and current:
            chunks.append(" ".join(current))
            # Keep overlap
            overlap_words: list[str] = []
            overlap_count = 0
            for w in reversed(current):
                wt = count_tokens(w + " ")
                if overlap_count + wt > overlap_tokens:
                    break
                overlap_words.insert(0, w)
                overlap_count += wt
            current = overlap_words
            current_tokens = overlap_count
        current.append(word)
        current_tokens += word_tokens

    if current:
        chunks.append(" ".join(current))
    return chunks


class RetrievalService:
    def __init__(
        self,
        llm: LLMService,
        graph: GraphService,
        vector: VectorService,
        memory: MemoryService,
        ner=None,
    ):
        self.llm = llm
        self.graph = graph
        self.vector = vector
        self.memory = memory
        self.ner = ner  # NERService or None

    # ========================
    # INGESTION PIPELINE
    # ========================

    async def ingest_text(
        self,
        text: str,
        source_type: str = "note",
        tags: list[str] | None = None,
        topic: str | None = None,
        file_hash: str | None = None,
    ) -> dict:
        """Full Contextual Retrieval ingestion pipeline.

        1. Translate Arabic -> English
        2. Split into chunks
        3. Contextual enrichment (LLM adds context to each chunk)
        4. Embed + store in Qdrant
        5. Extract facts + store in FalkorDB (parallel with step 3-4)
        """
        # Step 1: Translate (skip if text is already mostly English)
        if _is_mostly_english(text):
            text_en = text
        else:
            text_en = await self.llm.translate_to_english(text)

        # Step 2: Chunk
        chunks = chunk_text(text_en)
        if not chunks:
            return {"chunks_stored": 0, "facts_extracted": 0}

        # Steps 3-5 in parallel
        enrichment_task = self._enrich_and_store_chunks(
            chunks, text_en, text, source_type, tags, topic, file_hash
        )
        facts_task = self._extract_and_store_facts(text_en)

        chunks_stored, (facts_stored, entities) = await asyncio.gather(
            enrichment_task, facts_task
        )

        return {
            "chunks_stored": chunks_stored,
            "facts_extracted": facts_stored,
            "entities": entities,
        }

    async def _enrich_and_store_chunks(
        self,
        chunks: list[str],
        full_doc_en: str,
        original_ar: str,
        source_type: str,
        tags: list[str] | None,
        topic: str | None,
        file_hash: str | None = None,
    ) -> int:
        # Contextual enrichment — enrich all chunks in parallel (vLLM continuous batching)
        async def _enrich_one(chunk: str) -> str:
            try:
                return await self.llm.add_context_to_chunk(chunk, full_doc_en)
            except Exception as e:
                logger.warning("Chunk enrichment failed, using raw: %s", e)
                return chunk

        enriched = list(await asyncio.gather(*[_enrich_one(c) for c in chunks]))

        base_meta = {
            "source_type": source_type,
            "tags": tags or [],
            "topic": topic or "",
            "original_text_ar": original_ar[:500],
            **({"file_hash": file_hash} if file_hash else {}),
        }
        metadata_list = [dict(base_meta) for _ in enriched]

        return await self.vector.upsert_chunks(enriched, metadata_list)

    async def _extract_and_store_facts(self, text_en: str) -> tuple[int, list[dict]]:
        # For large texts, extract from each chunk individually then merge
        tokens = count_tokens(text_en)
        if tokens <= 3000:
            facts = await self.llm.extract_facts(text_en)
            count = await self.graph.upsert_from_facts(facts)
            return count, facts.get("entities", [])

        # Chunk and extract in parallel
        chunks = chunk_text(text_en, max_tokens=3000, overlap_tokens=200)
        logger.info("Large text (%d tokens) → %d chunks for extraction", tokens, len(chunks))

        chunk_facts = await asyncio.gather(
            *[self.llm.extract_facts(chunk) for chunk in chunks]
        )

        # Merge and dedup entities by (entity_type, entity_name)
        seen = set()
        merged_entities = []
        for facts in chunk_facts:
            for entity in facts.get("entities", []):
                key = (entity.get("entity_type", ""), entity.get("entity_name", ""))
                if key not in seen:
                    seen.add(key)
                    merged_entities.append(entity)

        merged = {"entities": merged_entities}
        count = await self.graph.upsert_from_facts(merged)
        return count, merged_entities

    # ========================
    # NER
    # ========================

    async def _run_ner(self, text_ar: str) -> str:
        """Run NER on Arabic text, return formatted hints or empty string."""
        if not self.ner:
            return ""
        try:
            entities = self.ner.extract_entities(text_ar)
            hints = self.ner.format_hints(entities)
            if hints:
                logger.info("NER hints: %s", hints)
            return hints
        except Exception as e:
            logger.debug("NER failed: %s", e)
            return ""

    # ========================
    # DIRECT SEARCH
    # ========================

    async def search_direct(
        self,
        query: str,
        source: str = "auto",
        limit: int = 5,
    ) -> dict:
        """Direct search without generating a response."""
        query_en = await self.llm.translate_to_english(query)

        results = []
        source_used = source

        if source == "vector" or source == "auto":
            vector_results = await self.vector.search(query_en, limit=limit)
            for r in vector_results:
                results.append({
                    "text": r["text"],
                    "score": r["score"],
                    "source": "vector",
                    "metadata": r["metadata"],
                })
            source_used = "vector"

        if source == "graph" or (source == "auto" and len(results) < 2):
            graph_text = await self.graph.search_nodes(query_en, limit=limit)
            if graph_text:
                results.append({
                    "text": graph_text,
                    "score": 1.0,
                    "source": "graph",
                    "metadata": {},
                })
                source_used = "graph" if source == "graph" else "hybrid"

        return {"results": results, "source_used": source_used}
