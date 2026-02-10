import asyncio
import logging
import re

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


def chunk_text(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
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


# --- Smart Router (keyword-based, no LLM call) ---

# --- Finer-grained keyword patterns (checked in specificity order) ---

# Debt payment (most specific financial sub-route)
DEBT_PAYMENT_KEYWORDS = re.compile(
    r"(سدد|رجع.?الفلوس|دفع له|دفع لها|رد.?المبلغ|"
    r"settled|paid back|returned the money|paid him|paid her)",
    re.IGNORECASE,
)

# Debt queries
DEBT_QUERY_KEYWORDS = re.compile(
    r"(ديون|يطلبني|أطلب|اطلب|يطلبه|مديون|"
    r"who owe|outstanding|debt summary|owed to me|i owe)",
    re.IGNORECASE,
)

# Financial report / monthly summary
FINANCIAL_REPORT_KEYWORDS = re.compile(
    r"(ملخص|تقرير|مصاريف الشهر|مصاريف شهر|مقارنة|كم صرفت|"
    r"report|summary|monthly.*spend|spend.*month|spending.*month|compare.*month|how much.*spend)",
    re.IGNORECASE,
)

# General financial (fallback)
FINANCIAL_KEYWORDS = re.compile(
    r"(صرفت|دفعت|مصاريف|فلوس|ريال|حساب|ميزانية|"
    r"spend|spent|expense|money|budget|salary|cost|paid|payment)",
    re.IGNORECASE,
)

# Reminder action (done/snooze/cancel)
REMINDER_ACTION_KEYWORDS = re.compile(
    r"(خلصت|تم التذكير|تمت المهمة|أجّل|أجلي|الغي التذكير|الغاء|"
    r"\bdone\b|\bsnooze\b|\bcancel\b|\bcomplete\b|\bfinished\b|\bpostpone\b)",
    re.IGNORECASE,
)

REMINDER_KEYWORDS = re.compile(
    r"(ذكرني|موعد|تذكير|تنبيه|لا تنساني|alarm|remind|reminder|appointment|schedule|deadline|don't forget)",
    re.IGNORECASE,
)

PROJECT_KEYWORDS = re.compile(
    r"(مشروع|تقدم|مرحلة|project|progress|milestone|sprint|status)",
    re.IGNORECASE,
)

PERSON_KEYWORDS = re.compile(
    r"(مين|القصة مع|تعرف|who|person|contact|relationship|friend|colleague)",
    re.IGNORECASE,
)

TASK_KEYWORDS = re.compile(
    r"(مهمة|مهام|لازم اسوي|task|todo|to-do|action item)",
    re.IGNORECASE,
)


def smart_route(text: str) -> str:
    """Route query to the best source based on keywords.
    More specific routes checked first to avoid false matches.
    """
    # Financial sub-routes (most specific first)
    if DEBT_PAYMENT_KEYWORDS.search(text):
        return "graph_debt_payment"
    if DEBT_QUERY_KEYWORDS.search(text):
        return "graph_debt_summary"
    if FINANCIAL_REPORT_KEYWORDS.search(text):
        return "graph_financial_report"
    if FINANCIAL_KEYWORDS.search(text):
        return "graph_financial"

    # Reminder sub-routes
    if REMINDER_ACTION_KEYWORDS.search(text) and REMINDER_KEYWORDS.search(text):
        return "graph_reminder_action"
    if REMINDER_KEYWORDS.search(text):
        return "graph_reminder"

    if PROJECT_KEYWORDS.search(text):
        return "graph_project"
    if PERSON_KEYWORDS.search(text):
        return "graph_person"
    if TASK_KEYWORDS.search(text):
        return "graph_task"
    return "llm_classify"


class RetrievalService:
    def __init__(
        self,
        llm: LLMService,
        graph: GraphService,
        vector: VectorService,
        memory: MemoryService,
    ):
        self.llm = llm
        self.graph = graph
        self.vector = vector
        self.memory = memory
        self.max_context_tokens = 15000

    # ========================
    # INGESTION PIPELINE
    # ========================

    async def ingest_text(
        self,
        text: str,
        source_type: str = "note",
        tags: list[str] | None = None,
        topic: str | None = None,
    ) -> dict:
        """Full Contextual Retrieval ingestion pipeline.

        1. Translate Arabic -> English
        2. Split into chunks
        3. Contextual enrichment (LLM adds context to each chunk)
        4. Embed + store in Qdrant
        5. Extract facts + store in FalkorDB (parallel with step 3-4)
        """
        # Step 1: Translate
        text_en = await self.llm.translate_to_english(text)

        # Step 2: Chunk
        chunks = chunk_text(text_en)
        if not chunks:
            return {"chunks_stored": 0, "facts_extracted": 0}

        # Steps 3-5 in parallel
        enrichment_task = self._enrich_and_store_chunks(
            chunks, text_en, text, source_type, tags, topic
        )
        facts_task = self._extract_and_store_facts(text_en)

        chunks_stored, facts_stored = await asyncio.gather(
            enrichment_task, facts_task
        )

        return {"chunks_stored": chunks_stored, "facts_extracted": facts_stored}

    async def _enrich_and_store_chunks(
        self,
        chunks: list[str],
        full_doc_en: str,
        original_ar: str,
        source_type: str,
        tags: list[str] | None,
        topic: str | None,
    ) -> int:
        # Contextual enrichment — enrich each chunk with document context
        enriched = []
        for chunk in chunks:
            try:
                enriched_chunk = await self.llm.add_context_to_chunk(chunk, full_doc_en)
                enriched.append(enriched_chunk)
            except Exception as e:
                logger.warning("Chunk enrichment failed, using raw: %s", e)
                enriched.append(chunk)

        metadata_list = [
            {
                "source_type": source_type,
                "tags": tags or [],
                "topic": topic or "",
                "original_text_ar": original_ar[:500],
            }
            for _ in enriched
        ]

        return await self.vector.upsert_chunks(enriched, metadata_list)

    async def _extract_and_store_facts(self, text_en: str) -> int:
        facts = await self.llm.extract_facts(text_en)
        return await self.graph.upsert_from_facts(facts)

    # ========================
    # RETRIEVAL PIPELINE (Agentic RAG)
    # ========================

    async def retrieve_and_respond(
        self, query_ar: str, session_id: str = "default"
    ) -> dict:
        """Agentic RAG pipeline: Think → Act → Reflect (with Self-RAG).

        1. Translate query Arabic → English
        2. FAST PATH: keyword router — if match, skip Think step
        3. THINK (if no keyword match): LLM decides strategy + search queries
        4. ACT: execute retrieval strategy → context_parts, sources
        5. REFLECT + Self-RAG: LLM scores chunks, filter below threshold
        6. RETRY (if !sufficient && retries > 0): flip strategy, merge results
        7. Build context (memory + filtered chunks, ≤15K tokens)
        8. Generate Arabic response
        9. Return reply + sources + route + agentic_trace
        """
        agentic_trace: list[dict] = []

        # Step 1: Translate
        query_en = await self.llm.translate_to_english(query_ar)

        # Step 2: Fast path — keyword router
        route = smart_route(query_ar)
        if route == "llm_classify":
            route = smart_route(query_en)

        used_fast_path = route != "llm_classify"

        if used_fast_path:
            # Fast path: keyword matched, skip Think step
            agentic_trace.append({
                "step": "route",
                "method": "fast_path_keyword",
                "strategy": route,
            })
            search_queries = [query_en]
        else:
            # Step 3: THINK — LLM decides strategy
            think_result = await self.llm.think_step(query_en)
            route = think_result.get("strategy", "vector")
            search_queries = think_result.get("search_queries", [query_en])
            if not search_queries:
                search_queries = [query_en]
            agentic_trace.append({
                "step": "think",
                "strategy": route,
                "search_queries": search_queries,
                "reasoning": think_result.get("reasoning", ""),
            })

        # Step 4: ACT — execute retrieval
        context_parts, sources = await self._execute_retrieval_strategy(
            route, query_en, search_queries
        )
        agentic_trace.append({
            "step": "act",
            "strategy": route,
            "chunks_retrieved": len(context_parts),
            "sources": list(set(sources)),
        })

        # Step 5: REFLECT + Self-RAG (score chunks, filter low-relevance)
        filtered_parts = context_parts
        if context_parts:
            reflect_result = await self.llm.reflect_step(query_en, context_parts)
            chunk_scores = reflect_result.get("chunk_scores", [])
            sufficient = reflect_result.get("sufficient", True)

            # Filter chunks below threshold
            threshold = settings.self_rag_threshold
            if chunk_scores:
                scored_parts = []
                for cs in chunk_scores:
                    idx = cs.get("index", -1)
                    score = cs.get("score", 1.0)
                    if 0 <= idx < len(context_parts) and score >= threshold:
                        scored_parts.append(context_parts[idx])
                # Keep at least 1 chunk if all filtered out
                filtered_parts = scored_parts if scored_parts else context_parts[:1]
            else:
                filtered_parts = context_parts

            agentic_trace.append({
                "step": "reflect",
                "sufficient": sufficient,
                "chunk_scores": chunk_scores,
                "chunks_after_filter": len(filtered_parts),
                "threshold": threshold,
            })

            # Step 6: RETRY if insufficient and retries available
            if not sufficient and settings.agentic_max_retries > 0:
                retry_strategy = self._parse_retry_hint(
                    reflect_result.get("retry_strategy"), route
                )
                agentic_trace.append({
                    "step": "retry",
                    "original_strategy": route,
                    "retry_strategy": retry_strategy,
                })
                retry_parts, retry_sources = await self._execute_retrieval_strategy(
                    retry_strategy, query_en, search_queries
                )
                # Merge new results (deduplicate)
                existing_set = set(filtered_parts)
                for rp in retry_parts:
                    if rp not in existing_set:
                        filtered_parts.append(rp)
                        existing_set.add(rp)
                sources.extend(retry_sources)

                agentic_trace.append({
                    "step": "retry_result",
                    "new_chunks": len(retry_parts),
                    "total_chunks": len(filtered_parts),
                })

        # Step 7: Build context with budget
        memory_context = await self.memory.build_memory_context(session_id)
        retrieved_context = "\n\n".join(filtered_parts)

        memory_tokens = count_tokens(memory_context)
        remaining = self.max_context_tokens - memory_tokens
        if count_tokens(retrieved_context) > remaining:
            words = retrieved_context.split()
            truncated: list[str] = []
            tokens_so_far = 0
            for w in words:
                wt = count_tokens(w + " ")
                if tokens_so_far + wt > remaining:
                    break
                truncated.append(w)
                tokens_so_far += wt
            retrieved_context = " ".join(truncated)

        # Step 8: Generate response
        reply = await self.llm.generate_response(
            query_ar, retrieved_context, memory_context
        )

        return {
            "reply": reply,
            "sources": list(set(sources)),
            "route": route,
            "query_en": query_en,
            "agentic_trace": agentic_trace,
        }

    async def _execute_retrieval_strategy(
        self, strategy: str, query_en: str, search_queries: list[str]
    ) -> tuple[list[str], list[str]]:
        """Execute a retrieval strategy and return (context_parts, sources)."""
        context_parts: list[str] = []
        sources: list[str] = []
        primary_query = search_queries[0] if search_queries else query_en

        if strategy.startswith("graph_"):
            graph_context = await self._retrieve_from_graph(strategy, primary_query)
            if graph_context:
                context_parts.append(graph_context)
                sources.append("graph")
            # Hybrid: also vector search
            vector_results = await self.vector.search(primary_query, limit=3)
            for r in vector_results:
                context_parts.append(r["text"])
                sources.append("vector")
        elif strategy == "hybrid":
            # Both graph search + vector search
            graph_text = await self.graph.search_nodes(primary_query, limit=5)
            if graph_text:
                context_parts.append(graph_text)
                sources.append("graph")
            for sq in search_queries:
                vector_results = await self.vector.search(sq, limit=3)
                for r in vector_results:
                    if r["text"] not in context_parts:
                        context_parts.append(r["text"])
                        sources.append("vector")
        else:
            # Vector search (default)
            for sq in search_queries:
                vector_results = await self.vector.search(sq, limit=5)
                for r in vector_results:
                    if r["text"] not in context_parts:
                        context_parts.append(r["text"])
                        sources.append("vector")
            # Also check graph
            graph_text = await self.graph.search_nodes(primary_query, limit=5)
            if graph_text:
                context_parts.append(graph_text)
                sources.append("graph")

        return context_parts, sources

    async def _retrieve_from_graph(self, route: str, query_en: str) -> str:
        if route == "graph_financial_report":
            from datetime import datetime
            now = datetime.utcnow()
            report = await self.graph.query_monthly_report(now.month, now.year)
            return self._format_monthly_report(report)
        elif route == "graph_debt_summary":
            summary = await self.graph.query_debt_summary()
            return self._format_debt_summary(summary)
        elif route == "graph_debt_payment":
            # Debt payment is handled via post-processing (DebtPayment entity extraction)
            # For retrieval, show current debt status for context
            summary = await self.graph.query_debt_summary()
            return self._format_debt_summary(summary)
        elif route == "graph_reminder_action":
            # Show current reminders for context (action handled in post-processing)
            return await self.graph.query_reminders()
        elif route == "graph_financial":
            return await self.graph.query_financial_summary()
        elif route == "graph_reminder":
            return await self.graph.query_reminders()
        elif route == "graph_project":
            return await self.graph.search_nodes(query_en, limit=3)
        elif route == "graph_person":
            return await self.graph.search_nodes(query_en, limit=5)
        elif route == "graph_task":
            q = "MATCH (t:Task) WHERE t.status <> 'done' RETURN t.title, t.status, t.due_date, t.priority ORDER BY t.priority DESC LIMIT 20"
            rows = await self.graph.query(q)
            if not rows:
                return "No active tasks found."
            parts = ["Active tasks:"]
            for r in rows:
                parts.append(f"  - {r[0]} [{r[1]}]")
            return "\n".join(parts)
        return ""

    @staticmethod
    def _format_debt_summary(summary: dict) -> str:
        parts = [
            f"Debt Summary: I owe {summary['total_i_owe']:.0f} SAR, "
            f"owed to me {summary['total_owed_to_me']:.0f} SAR, "
            f"net position {summary['net_position']:+.0f} SAR"
        ]
        for d in summary.get("debts", []):
            direction = "they owe me" if d["direction"] == "owed_to_me" else "I owe them"
            reason = f" ({d['reason']})" if d.get("reason") else ""
            status_tag = f" [{d['status']}]" if d["status"] != "open" else ""
            parts.append(f"  - {d['person']}: {d['amount']:.0f} SAR ({direction}){reason}{status_tag}")
        return "\n".join(parts) if parts else "No debts found."

    @staticmethod
    def _format_monthly_report(report: dict) -> str:
        parts = [f"Monthly Report ({report['month']}/{report['year']}): {report['total']:.0f} {report['currency']} total"]
        for cat in report.get("by_category", []):
            parts.append(f"  - {cat['category']}: {cat['total']:.0f} SAR ({cat['count']} items, {cat['percentage']}%)")
        if report.get("comparison"):
            comp = report["comparison"]
            parts.append(f"\nComparison vs {comp['previous_month']}/{comp['previous_year']}: "
                         f"{comp['difference']:+.0f} SAR ({comp['percentage_change']:+.1f}%)")
        return "\n".join(parts) if parts else "No expenses for this period."

    def _parse_retry_hint(self, hint: str | None, original: str) -> str:
        """Parse retry strategy from Reflect step, or flip to opposite."""
        valid = {
            "vector", "hybrid",
            "graph_financial", "graph_financial_report",
            "graph_debt_summary", "graph_debt_payment",
            "graph_reminder", "graph_reminder_action",
            "graph_project", "graph_person", "graph_task",
        }
        if hint and hint in valid and hint != original:
            return hint
        # Flip: if was graph-based, try vector; if vector, try hybrid
        if original.startswith("graph_"):
            return "vector"
        return "hybrid"

    # ========================
    # BACKGROUND POST-PROCESSING
    # ========================

    async def post_process(
        self, query_ar: str, reply_ar: str, session_id: str
    ) -> None:
        """Run after response is sent: update memory, extract facts, store embeddings."""
        try:
            # Update working memory
            await self.memory.push_message(session_id, "user", query_ar)
            await self.memory.push_message(session_id, "assistant", reply_ar)

            # Extract and store facts from the conversation
            combined = f"User said: {query_ar}\nAssistant replied: {reply_ar}"
            combined_en = await self.llm.translate_to_english(combined)
            facts = await self.llm.extract_facts(combined_en)
            if facts.get("entities"):
                await self.graph.upsert_from_facts(facts)

            # Store the exchange as a vector for future retrieval
            await self.vector.upsert_chunks(
                [combined_en],
                [{"source_type": "conversation", "topic": "chat"}],
            )
        except Exception as e:
            logger.error("Post-processing failed: %s", e)

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
