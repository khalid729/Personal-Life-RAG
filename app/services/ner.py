"""Arabic NER service — lazy-loaded HuggingFace pipeline with CAMeL BERT."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Entity group mapping from BIO tags to our graph entity types
_GROUP_MAP = {
    "PER": "Person",
    "LOC": "Location",
    "ORG": "Organization",
    "MISC": "Misc",
}

_executor = ThreadPoolExecutor(max_workers=1)


class NERService:
    def __init__(self):
        self._pipeline = None

    async def start(self):
        if not settings.arabic_ner_enabled:
            logger.info("Arabic NER disabled")
            return
        logger.info("Loading Arabic NER model: %s ...", settings.arabic_ner_model)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_executor, self._load_model)
        logger.info("Arabic NER model loaded")

    def _load_model(self):
        from transformers import pipeline

        self._pipeline = pipeline(
            "ner",
            model=settings.arabic_ner_model,
            aggregation_strategy="simple",
        )

    def extract_entities(self, text: str) -> list[dict]:
        if not self._pipeline or not text:
            return []
        try:
            raw = self._pipeline(text)
        except Exception as e:
            logger.warning("NER extraction failed: %s", e)
            return []

        entities = []
        for ent in raw:
            score = float(ent.get("score", 0))
            if score < 0.7:
                continue
            group = ent.get("entity_group", "")
            mapped = _GROUP_MAP.get(group, group)
            word = ent.get("word", "").strip()
            if not word or len(word) < 2:
                continue
            # Clean up sub-word tokens
            word = word.replace("##", "")
            entities.append({
                "entity_group": mapped,
                "word": word,
                "score": round(score, 3),
            })

        # Deduplicate by word
        seen = set()
        unique = []
        for e in entities:
            key = (e["entity_group"], e["word"])
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique

    def format_hints(self, entities: list[dict]) -> str:
        if not entities:
            return ""
        by_group: dict[str, list[str]] = {}
        for e in entities:
            by_group.setdefault(e["entity_group"], []).append(e["word"])
        parts = []
        for group, words in by_group.items():
            parts.append(f"{group}: {', '.join(words)}")
        return "Detected entities: " + "; ".join(parts)
