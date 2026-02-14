import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import tiktoken

from app.config import get_settings
from app.prompts.conversation import (
    NUMBER_SELECTION,
    is_confirmation,
    is_delete_intent,
)
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


def _now_local_str() -> str:
    tz = timezone(timedelta(hours=settings.timezone_offset_hours))
    return datetime.now(tz).strftime("%Y-%m-%d")


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
    r"(ملخص.*مالي|ملخص.*مصاريف|ملخص.*صرف|تقرير.*مالي|تقرير.*مصاريف|مصاريف الشهر|مصاريف شهر|مقارنة|كم صرفت|"
    r"financial.*report|financial.*summary|monthly.*spend|spend.*month|spending.*month|compare.*month|how much.*spend)",
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
    r"(خلصت|خلصته|تم التذكير|تمت المهمة|أجّل|أجلي|الغي التذكير|الغاء|"
    r"استلمت|سلمت|أنجزت|أنجزته|سويت|سويته|وصلني|"
    r"\bdone\b|\bsnooze\b|\bcancel\b|\bcomplete\b|\bfinished\b|\bpostpone\b|"
    r"\bpicked up\b|\breceived\b|\bcompleted\b)",
    re.IGNORECASE,
)

REMINDER_KEYWORDS = re.compile(
    r"(ذكرني|موعد|تذكير|تنبيه|لا تنساني|alarm|remind|reminder|appointment|schedule|deadline|don't forget)",
    re.IGNORECASE,
)

DAILY_PLAN_KEYWORDS = re.compile(
    r"(رتب.*يومي|خطة اليوم|خطط.*يومي|يومي ايش|ملخص.*يوم|ملخص.*عمل|وش عندي اليوم|وش عندي.*اليوم|"
    r"أعمال اليوم|مهام اليوم|جدول اليوم|اللي عندي اليوم|"
    r"plan my day|daily plan|today.?s plan|what.?s on|today.?s tasks|what do I have today)",
    re.IGNORECASE,
)

KNOWLEDGE_KEYWORDS = re.compile(
    r"(معلومة|احفظ.?لي|أعرف عن|اعرف عن|وش أعرف|knowledge|what do I know|info about)",
    re.IGNORECASE,
)

SPRINT_KEYWORDS = re.compile(
    r"(سبرنت|burndown|velocity|iteration|sprint\b)",
    re.IGNORECASE,
)

FOCUS_KEYWORDS = re.compile(
    r"(focus|pomodoro|بومودورو|تركيز|جلسة عمل|focus stats|إحصائيات.*تركيز)",
    re.IGNORECASE,
)

TIMEBLOCK_KEYWORDS = re.compile(
    r"(رتب.*وقت|جدول.*مهام|time.?block|schedule.*tasks|خطة.*مهام.*وقت)",
    re.IGNORECASE,
)

PRODUCTIVITY_KEYWORDS = re.compile(
    r"(إنتاجية|إنتاجيتي|productivity stats|how productive|ملخص.*إنتاج)",
    re.IGNORECASE,
)

PROJECT_KEYWORDS = re.compile(
    r"(مشروع|تقدم|مرحلة|project|progress|milestone|status)",
    re.IGNORECASE,
)

PERSON_KEYWORDS = re.compile(
    r"(مين|القصة مع|تعرف|بناتي|أولادي|عيالي|عائلتي|أبوي|أمي|زوجتي|أخوي|اسم\b.*\b(بنت|ولد|زوج)|who|person|contact|relationship|friend|colleague|family|daughter|son|wife|husband|children)",
    re.IGNORECASE,
)

TASK_KEYWORDS = re.compile(
    r"(مهمة|مهام|لازم اسوي|task|todo|to-do|action item)",
    re.IGNORECASE,
)

INVENTORY_MOVE_KEYWORDS = re.compile(
    r"(نقلت|حركت|حطيته في|حطيتها في|شلته من|نقله|حوّل|moved|relocated|transferred|put it in)",
    re.IGNORECASE,
)

INVENTORY_USAGE_KEYWORDS = re.compile(
    r"(استخدمت|ضاع|خلص|عطيت|انكسر|رميت|used .+ (cable|item|tool|بطارية|كيبل)|gave away|lost|broke)",
    re.IGNORECASE,
)

INVENTORY_DUPLICATE_KEYWORDS = re.compile(
    r"(أغراض مكررة|مكرر.*مخزون|duplicate.*item|duplicate.*inventory|نفس الغرض)",
    re.IGNORECASE,
)

INVENTORY_REPORT_KEYWORDS = re.compile(
    r"(تقرير.*مخزون|تقرير.*أغراض|inventory report|inventory stats|إحصائيات.*مخزون|ملخص.*أغراض)",
    re.IGNORECASE,
)

INVENTORY_UNUSED_KEYWORDS = re.compile(
    r"(ما استخدمت|منسي|مهمل|unused|forgotten|neglected|not used|أغراض قديمة)",
    re.IGNORECASE,
)

INVENTORY_KEYWORDS = re.compile(
    r"(مخزون|جرد|أغراضي|حوائجي|وين ال|فين ال|عندي\b|شريت\b|اشتريت\b|جبت\b|inventory|items|stock|where is|do i have|how many .+ do i|i bought|i got a|i have a)",
    re.IGNORECASE,
)


def smart_route(text: str) -> str:
    """Route query to the best source based on keywords.
    More specific routes checked first to avoid false matches.
    """
    # Daily plan (check before financial — "ملخص اليوم" != "ملخص مالي")
    if DAILY_PLAN_KEYWORDS.search(text):
        return "graph_daily_plan"

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
    if REMINDER_ACTION_KEYWORDS.search(text):
        return "graph_reminder_action"
    if REMINDER_KEYWORDS.search(text):
        return "graph_reminder"
    if KNOWLEDGE_KEYWORDS.search(text):
        return "graph_knowledge"

    if SPRINT_KEYWORDS.search(text):
        return "graph_sprint"
    if FOCUS_KEYWORDS.search(text):
        return "graph_focus_stats"
    if TIMEBLOCK_KEYWORDS.search(text):
        return "graph_timeblock"
    if PRODUCTIVITY_KEYWORDS.search(text):
        return "graph_productivity_report"
    if PROJECT_KEYWORDS.search(text):
        return "graph_project"
    if PERSON_KEYWORDS.search(text):
        return "graph_person"
    if TASK_KEYWORDS.search(text):
        return "graph_task"
    if INVENTORY_DUPLICATE_KEYWORDS.search(text):
        return "graph_inventory_duplicates"
    if INVENTORY_REPORT_KEYWORDS.search(text):
        return "graph_inventory_report"
    if INVENTORY_MOVE_KEYWORDS.search(text):
        return "graph_inventory"
    if INVENTORY_USAGE_KEYWORDS.search(text):
        return "graph_inventory"
    if INVENTORY_UNUSED_KEYWORDS.search(text):
        return "graph_inventory_unused"
    if INVENTORY_KEYWORDS.search(text):
        return "graph_inventory"
    return "llm_classify"


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
    # RETRIEVAL PIPELINE (Agentic RAG)
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

    @staticmethod
    def _build_extraction_summary(facts: dict, count: int) -> str:
        """Build short summary of what was extracted for the responder."""
        if count == 0:
            return ""
        lines = []
        for e in facts.get("entities", []):
            etype = e.get("entity_type", "")
            ename = e.get("entity_name", "")
            props = e.get("properties", {})
            if etype == "Reminder":
                due = props.get("due_date", "")
                lines.append(f"CREATED reminder: {ename} (due: {due})")
            elif etype == "ReminderAction":
                action = props.get("action", "done")
                title = props.get("reminder_title", ename)
                lines.append(f"MARKED reminder {action}: {title}")
            elif etype == "Expense":
                amt = props.get("amount", "")
                lines.append(f"RECORDED expense: {ename} ({amt} SAR)")
            elif etype == "DebtPayment":
                lines.append(f"RECORDED debt payment: {ename}")
            elif etype == "Debt":
                amt = props.get("amount", "")
                direction = props.get("direction", "")
                lines.append(f"RECORDED debt: {ename} ({amt} SAR, {direction})")
            elif etype == "Item":
                qty = props.get("quantity", 1)
                lines.append(f"STORED item: {ename} (qty: {qty})")
            elif etype == "ItemMove":
                to_loc = props.get("to_location", "")
                lines.append(f"MOVED item: {ename} → {to_loc}")
            elif etype == "ItemUsage":
                qty = props.get("quantity_used", 1)
                lines.append(f"USED item: {ename} (qty: {qty})")
            else:
                lines.append(f"STORED {etype}: {ename}")
        return "\n".join(lines)

    async def _prepare_context(
        self, query_ar: str, session_id: str = "default"
    ) -> dict:
        """Multi-agent pipeline: parallel translate+NER+route → parallel extract+retrieve → build context.

        Returns a dict with all context needed for response generation (or an early return).
        If 'early_return' is set, the caller should return that dict directly.
        """
        agentic_trace: list[dict] = []

        # --- A. Confirmation pre-check ---
        if settings.confirmation_enabled:
            pending = await self.memory.get_pending_action(session_id)
            if pending:
                confirmation = is_confirmation(query_ar.strip())
                if confirmation == "yes":
                    result = await self._execute_confirmed_action(pending, session_id)
                    if not pending.get("disambiguation_options"):
                        await self.memory.clear_pending_action(session_id)
                    return {"early_return": {
                        "reply": result,
                        "sources": [],
                        "route": pending.get("route", ""),
                        "query_en": pending.get("query_en", ""),
                        "agentic_trace": [{"step": "confirmed_action", "action_type": pending.get("action_type")}],
                        "pending_confirmation": bool(pending.get("disambiguation_options")),
                    }}
                elif confirmation == "no":
                    await self.memory.clear_pending_action(session_id)
                    return {"early_return": {
                        "reply": "تمام، ما سويت شي.",
                        "sources": [],
                        "route": pending.get("route", ""),
                        "query_en": "",
                        "agentic_trace": [{"step": "cancelled_action"}],
                    }}
                elif NUMBER_SELECTION.match(query_ar.strip()):
                    result = await self._resolve_disambiguation(pending, int(query_ar.strip()))
                    await self.memory.clear_pending_action(session_id)
                    return {"early_return": {
                        "reply": result,
                        "sources": [],
                        "route": pending.get("route", ""),
                        "query_en": pending.get("query_en", ""),
                        "agentic_trace": [{"step": "disambiguation_resolved"}],
                    }}
                else:
                    await self.memory.clear_pending_action(session_id)

        # Auto-compress working memory if threshold exceeded
        msg_count = await self.memory.get_working_memory_count(session_id)
        if msg_count > settings.conversation_compress_threshold:
            try:
                old_messages = await self.memory.compress_working_memory(
                    session_id, settings.conversation_compress_keep_recent
                )
                if old_messages:
                    summary = await self.llm.summarize_conversation(old_messages)
                    await self.memory.save_conversation_summary(session_id, summary)
                    logger.info("Compressed %d messages into summary for %s", len(old_messages), session_id)
            except Exception as e:
                logger.warning("Conversation compression failed: %s", e)

        # === Stage 1: Parallel translate + NER + route ===
        translate_coro = self.llm.translate_to_english(query_ar)
        ner_coro = self._run_ner(query_ar)

        query_en, ner_hints = await asyncio.gather(translate_coro, ner_coro)

        # Route (keyword-based, no LLM)
        route = smart_route(query_ar)
        if route == "llm_classify":
            route = smart_route(query_en)

        used_fast_path = route != "llm_classify"

        if used_fast_path:
            agentic_trace.append({
                "step": "route",
                "method": "fast_path_keyword",
                "strategy": route,
            })
            search_queries = [query_en]
        else:
            # Fallback: use think_step (LLM classify)
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

        # --- B. Confirmation (DELETE actions only) ---
        if (
            settings.confirmation_enabled
            and is_delete_intent(query_ar)
        ):
            target = self._extract_delete_target(query_ar)
            confirm_msg = f"تبيني أحذف: {target}؟" if target else f"تبيني أنفذ: {query_ar}؟"
            pending_action = {
                "action_type": "delete",
                "query_ar": query_ar,
                "query_en": query_en,
                "route": route,
                "delete_target": target,
                "created_at": datetime.utcnow().isoformat(),
                "confirmation_message": confirm_msg,
            }
            await self.memory.set_pending_action(session_id, pending_action)
            agentic_trace.append({"step": "confirmation_requested", "action_type": "delete"})
            return {"early_return": {
                "reply": confirm_msg,
                "sources": [],
                "route": route,
                "query_en": query_en,
                "agentic_trace": agentic_trace,
                "pending_confirmation": True,
            }}

        # === Stage 2: Parallel extract + retrieve ===
        extract_coro = self.llm.extract_facts_specialized(query_en, route, ner_hints)
        retrieve_coro = self._execute_retrieval_strategy(route, query_en, search_queries)

        facts, (context_parts, sources) = await asyncio.gather(
            extract_coro, retrieve_coro
        )

        agentic_trace.append({
            "step": "act",
            "strategy": route,
            "chunks_retrieved": len(context_parts),
            "sources": list(set(sources)),
        })

        # Upsert extracted facts immediately
        extraction_summary = ""
        if facts.get("entities"):
            count = await self.graph.upsert_from_facts(facts)
            extraction_summary = self._build_extraction_summary(facts, count)
            agentic_trace.append({
                "step": "extract",
                "entities": len(facts["entities"]),
                "upserted": count,
            })

        # --- C. Build context ---
        memory_context = await self.memory.build_system_memory_context(session_id)

        # Include conversation summary if available
        conv_summary = await self.memory.get_conversation_summary(session_id)
        if conv_summary:
            memory_context += f"\n\n=== Conversation Summary ===\n{conv_summary}"

        conversation_history = await self.memory.get_conversation_turns(session_id)
        retrieved_context = "\n\n".join(context_parts)

        # Token budget
        memory_tokens = count_tokens(memory_context)
        history_tokens = sum(count_tokens(t.get("content", "")) for t in conversation_history)
        remaining = self.max_context_tokens - memory_tokens - history_tokens
        if remaining < 0:
            remaining = 500
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

        return {
            "context": retrieved_context,
            "memory_context": memory_context,
            "extraction_summary": extraction_summary,
            "conversation_history": conversation_history,
            "route": route,
            "query_en": query_en,
            "sources": list(set(sources)),
            "agentic_trace": agentic_trace,
        }

    async def retrieve_and_respond(
        self, query_ar: str, session_id: str = "default"
    ) -> dict:
        """Multi-agent pipeline with confirmation flow + multi-turn history."""
        ctx = await self._prepare_context(query_ar, session_id)

        if "early_return" in ctx:
            return ctx["early_return"]

        reply = await self.llm.generate_response(
            query_ar, ctx["context"], ctx["memory_context"],
            conversation_history=ctx["conversation_history"],
            extraction_summary=ctx.get("extraction_summary", ""),
        )

        return {
            "reply": reply,
            "sources": ctx["sources"],
            "route": ctx["route"],
            "query_en": ctx["query_en"],
            "agentic_trace": ctx["agentic_trace"],
        }

    async def retrieve_and_respond_stream(
        self, query_ar: str, session_id: str = "default"
    ):
        """Streaming version — yields NDJSON lines."""
        import json as _json

        ctx = await self._prepare_context(query_ar, session_id)

        if "early_return" in ctx:
            early = ctx["early_return"]
            meta = {
                "type": "meta",
                "route": early.get("route", ""),
                "sources": early.get("sources", []),
            }
            if early.get("pending_confirmation"):
                meta["pending_confirmation"] = True
            yield _json.dumps(meta) + "\n"
            yield _json.dumps({"type": "token", "content": early["reply"]}) + "\n"
            yield _json.dumps({"type": "done"}) + "\n"
            # Fire post-processing
            asyncio.create_task(self.post_process(
                query_ar, early["reply"], session_id,
                query_en=early.get("query_en"),
                skip_fact_extraction=early.get("pending_confirmation", False),
            ))
            return

        # Emit metadata
        yield _json.dumps({
            "type": "meta",
            "route": ctx["route"],
            "sources": ctx["sources"],
        }) + "\n"

        # Stream tokens
        full_reply = []
        async for chunk in self.llm.generate_response_stream(
            query_ar, ctx["context"], ctx["memory_context"],
            conversation_history=ctx["conversation_history"],
            extraction_summary=ctx.get("extraction_summary", ""),
        ):
            full_reply.append(chunk)
            yield _json.dumps({"type": "token", "content": chunk}) + "\n"

        yield _json.dumps({"type": "done"}) + "\n"

        # Fire post-processing in background
        reply_text = "".join(full_reply)
        asyncio.create_task(self.post_process(
            query_ar, reply_text, session_id,
            query_en=ctx.get("query_en"),
        ))

    _DELETE_STRIP_RE = re.compile(
        r"(احذف|حذف|امحي|امسح|شيل|ازل|الغي|الغاء|كنسل|فك|"
        r"delete|remove|cancel|erase|clear|drop|wipe)\s*",
        re.IGNORECASE,
    )
    _DELETE_NOUN_RE = re.compile(
        r"(تذكير|التذكير|المصروف|مصروف|الغرض|غرض|الدين|دين|"
        r"reminder|expense|item|debt)\s*",
        re.IGNORECASE,
    )

    def _extract_delete_target(self, query_ar: str) -> str:
        """Extract the target name from a delete query by stripping delete keywords."""
        cleaned = self._DELETE_STRIP_RE.sub("", query_ar)
        cleaned = self._DELETE_NOUN_RE.sub("", cleaned)
        return cleaned.strip()

    async def _execute_confirmed_action(self, pending: dict, session_id: str) -> str:
        """Execute a previously confirmed action."""
        action_type = pending.get("action_type", "")

        # --- Handle delete actions ---
        if action_type == "delete":
            return await self._execute_delete_action(pending)

        entities = pending.get("extracted_entities", [])
        if not entities:
            return "ما قدرت أنفذ العملية، حاول مرة ثانية."

        try:
            # For DebtPayment, handle disambiguation
            if action_type == "DebtPayment":
                entity = entities[0]
                props = entity.get("properties", {})
                rels = entity.get("relationships", [])
                person = ""
                for r in rels:
                    if r.get("target_type") == "Person":
                        person = r.get("target_name", "")
                        break
                amount = props.get("amount", 0)
                direction = props.get("direction")
                if person and amount > 0:
                    result = await self.graph.record_debt_payment(person, float(amount), direction)
                    if result.get("disambiguation_needed"):
                        # Store disambiguation options back as pending
                        options = result["options"]
                        lines = ["عندك أكثر من دين مع هالشخص، اختر الرقم:"]
                        for opt in options:
                            direction_ar = "لك عليه" if opt["direction"] == "owed_to_me" else "عليك له"
                            reason = f" ({opt['reason']})" if opt.get("reason") else ""
                            lines.append(f"{opt['index']}) {opt['current_amount']:.0f} ريال {direction_ar}{reason}")
                        pending["disambiguation_options"] = options
                        # Re-store pending so user can pick a number
                        await self.memory.set_pending_action(session_id, pending)
                        return "\n".join(lines)
                    if "error" in result:
                        return f"ما قدرت أسجل السداد: {result['error']}"
                    status_ar = "مسدد بالكامل" if result["status"] == "paid" else f"باقي {result['remaining']:.0f} ريال"
                    return f"تم تسجيل سداد {result['person']} بمبلغ {result['paid']:.0f} ريال. ({status_ar})"
                return "ما قدرت أنفذ العملية — معلومات ناقصة."

            # For other types, use upsert_from_facts
            facts = {"entities": entities}
            count = await self.graph.upsert_from_facts(facts)
            if count > 0:
                labels = {
                    "Expense": "المصروف",
                    "Debt": "الدين",
                    "Reminder": "التذكير",
                    "Item": "الغرض",
                    "ItemUsage": "استخدام الغرض",
                    "ItemMove": "نقل الغرض",
                }
                label = labels.get(action_type, "العملية")
                reply = f"تم تسجيل {label} بنجاح."
                # Purchase alert: check if similar item exists in inventory
                if action_type == "Expense":
                    item_name = entities[0].get("entity_name", "")
                    if item_name:
                        try:
                            similar = await self.graph.find_similar_items(item_name)
                            if similar:
                                items_text = ", ".join(
                                    f"{s['name']} ({s['quantity']} حبة)" for s in similar
                                )
                                reply += f"\n\n⚠️ تنبيه: عندك في المخزون: {items_text}"
                        except Exception as e:
                            logger.debug("Purchase alert check failed: %s", e)
                return reply
            return "ما قدرت أسجل العملية، حاول مرة ثانية."
        except Exception as e:
            logger.error("Confirmed action failed: %s", e)
            return "صار خطأ وأنا أنفذ العملية، حاول مرة ثانية."

    async def _resolve_disambiguation(self, pending: dict, choice: int) -> str:
        """Resolve a disambiguation selection (user picked a number)."""
        options = pending.get("disambiguation_options")
        if not options:
            return "ما في خيارات متاحة."

        selected = None
        for opt in options:
            if opt["index"] == choice:
                selected = opt
                break

        if not selected:
            return f"رقم غير صحيح. اختر رقم من 1 إلى {len(options)}."

        entity = pending.get("extracted_entities", [{}])[0]
        amount = entity.get("properties", {}).get("amount", 0)
        if not amount:
            return "ما قدرت أحدد المبلغ."

        result = await self.graph.apply_debt_payment_by_id(selected["debt_id"], float(amount))
        if "error" in result:
            return f"ما قدرت أسجل السداد: {result['error']}"

        status_ar = "مسدد بالكامل" if result["status"] == "paid" else f"باقي {result['remaining']:.0f} ريال"
        return f"تم تسجيل سداد {result['person']} بمبلغ {result['paid']:.0f} ريال. ({status_ar})"

    async def _execute_delete_action(self, pending: dict) -> str:
        """Execute a confirmed delete action."""
        target = pending.get("delete_target", "")
        route = pending.get("route", "")
        query_ar = pending.get("query_ar", "")

        try:
            # Translate target to English (reminders stored with English titles)
            target_en = await self.llm.translate_to_english(target) if target else ""

            # Reminder deletion — try Arabic first, then English
            if route in ("graph_reminder", "graph_reminder_action"):
                result = await self.graph.delete_reminder(target or query_ar)
                deleted = result.get("deleted", [])
                if not deleted and target_en:
                    result = await self.graph.delete_reminder(target_en)
                    deleted = result.get("deleted", [])
                if deleted:
                    return f"تم حذف {len(deleted)} تذكير: {', '.join(deleted)}"
                return "ما لقيت تذكير بهالاسم."

            # Inventory deletion
            if route == "graph_inventory":
                return "ما قدرت أحذف الغرض. استخدم أداة الحذف المخصصة."

            # Generic: pass through to LLM
            return "تم تنفيذ عملية الحذف."
        except Exception as e:
            logger.error("Delete action failed: %s", e)
            return "صار خطأ وأنا أنفذ الحذف، حاول مرة ثانية."

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
        elif route == "graph_daily_plan":
            return await self.graph.query_daily_plan()
        elif route == "graph_knowledge":
            return await self.graph.query_knowledge(query_en)
        elif route == "graph_project":
            ctx = await self.graph.query_projects_overview()
            if not ctx or "No projects found" in ctx:
                ctx = await self.graph.search_nodes(query_en, limit=3)
            return ctx
        elif route == "graph_person":
            ctx = await self.graph.query_person_context(query_en)
            if not ctx:
                ctx = await self.graph.search_nodes(query_en, limit=5)
            return ctx
        elif route == "graph_task":
            return await self.graph.query_active_tasks()
        elif route == "graph_inventory":
            ctx = await self.graph.query_inventory(query_en)
            # Touch last_used_at for queried items (best-effort)
            asyncio.create_task(self.graph._touch_item_last_used(query_en))
            return ctx
        elif route == "graph_inventory_unused":
            items = await self.graph.query_unused_items()
            if not items:
                return "لا يوجد أغراض مهملة."
            lines = [f"- {i['name']} ({i['category'] or '—'}) — {i['location'] or 'بدون مكان'}" for i in items]
            return "أغراض ما استخدمتها من فترة:\n" + "\n".join(lines)
        elif route == "graph_inventory_report":
            report = await self.graph.query_inventory_report()
            return self._format_inventory_report(report)
        elif route == "graph_inventory_duplicates":
            dups = await self.graph.detect_duplicate_items()
            if not dups:
                return "No duplicate items detected."
            lines = [f"- {d['item_a']['name']} ↔ {d['item_b']['name']}" for d in dups]
            return "Potential duplicates:\n" + "\n".join(lines)
        elif route == "graph_sprint":
            sprints = await self.graph.query_sprints(status_filter="active")
            if not sprints:
                sprints = await self.graph.query_sprints()
            if not sprints:
                return "No sprints found."
            parts = ["Sprints:"]
            for s in sprints:
                parts.append(
                    f"  - {s['name']} [{s['status']}] ({s['done_tasks']}/{s['total_tasks']} done, "
                    f"{s['progress_pct']}%) [{s['start_date']} → {s['end_date']}]"
                )
                if s.get("goal"):
                    parts.append(f"    Goal: {s['goal']}")
            return "\n".join(parts)
        elif route == "graph_focus_stats":
            stats = await self.graph.query_focus_stats()
            parts = [
                f"Focus stats: Today {stats['today_sessions']} sessions ({stats['today_minutes']} min), "
                f"Week {stats['week_sessions']} ({stats['week_minutes']} min), "
                f"Total {stats['total_sessions']} ({stats['total_minutes']} min)"
            ]
            for t in stats.get("by_task", []):
                parts.append(f"  - {t['task']}: {t['sessions']} sessions ({t['minutes']} min)")
            return "\n".join(parts)
        elif route == "graph_timeblock":
            # Detect energy override from query
            energy = None
            for word in ("tired", "تعبان", "مرهق"):
                if word in query_en.lower():
                    energy = "tired"
                    break
            for word in ("energized", "نشيط", "حماس"):
                if word in query_en.lower():
                    energy = "energized"
                    break
            today = _now_local_str()
            result = await self.graph.suggest_time_blocks(today, energy)
            if not result["blocks"]:
                return "No tasks to schedule."
            parts = [f"Time blocks ({result['energy_profile']} profile, {result['date']}):"]
            for b in result["blocks"]:
                start = b["start_time"][-8:-3]
                end = b["end_time"][-8:-3]
                parts.append(f"  [{start}-{end}] {b['task_title']} (energy:{b['energy_level']}, priority:{b['priority']})")
            return "\n".join(parts)
        elif route == "graph_productivity_report":
            parts = ["Productivity Report:"]
            # Tasks
            tasks = await self.graph.query_active_tasks()
            parts.append(tasks)
            # Focus
            stats = await self.graph.query_focus_stats()
            parts.append(
                f"\nFocus: {stats['today_sessions']} sessions today ({stats['today_minutes']} min), "
                f"{stats['week_sessions']} this week ({stats['week_minutes']} min)"
            )
            # Sprints
            sprints = await self.graph.query_sprints(status_filter="active")
            if sprints:
                for s in sprints:
                    parts.append(f"Sprint '{s['name']}': {s['progress_pct']}% ({s['done_tasks']}/{s['total_tasks']})")
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

    def _format_inventory_report(self, report: dict) -> str:
        parts = [f"Total: {report['total_items']} items ({report['total_quantity']} units)"]
        if report["by_category"]:
            parts.append("By category: " + ", ".join(f"{c['category']}({c['items']})" for c in report["by_category"]))
        if report["by_location"]:
            parts.append("By location: " + ", ".join(f"{loc['location']}({loc['items']})" for loc in report["by_location"]))
        if report["by_condition"]:
            parts.append("By condition: " + ", ".join(f"{c['condition']}({c['count']})" for c in report["by_condition"]))
        parts.append(f"Without location: {report['without_location']}")
        parts.append(f"Unused (>{settings.inventory_unused_days}d): {report['unused_count']}")
        if report["top_by_quantity"]:
            parts.append("Top by quantity: " + ", ".join(f"{t['name']}({t['quantity']})" for t in report["top_by_quantity"][:5]))
        return "\n".join(parts)

    # ========================
    # BACKGROUND POST-PROCESSING
    # ========================

    async def post_process(
        self,
        query_ar: str,
        reply_ar: str,
        session_id: str,
        query_en: str | None = None,
        skip_fact_extraction: bool = False,
    ) -> None:
        """Run after response is sent: update memory, store vector embeddings.

        Fact extraction has moved to the main pipeline (Stage 2).
        This only handles memory updates + vector storage + periodic tasks.
        """
        try:
            # Update working memory
            await self.memory.push_message(session_id, "user", query_ar)
            await self.memory.push_message(session_id, "assistant", reply_ar)

            # Increment message counter for periodic tasks
            msg_count = await self.memory.increment_message_count(session_id)

            if not skip_fact_extraction:
                # Translate only if not passed from pipeline
                if not query_en:
                    query_en = await self.llm.translate_to_english(query_ar)

                # Store the exchange as a vector for future retrieval
                combined_en = f"User: {query_en}\nAssistant: {reply_ar}"
                await self.vector.upsert_chunks(
                    [combined_en],
                    [{"source_type": "conversation", "topic": "chat"}],
                )

            # Periodic: daily summary
            if msg_count % settings.daily_summary_interval == 0:
                await self._trigger_daily_summary(session_id)

            # Periodic: core memory extraction
            if msg_count % settings.core_memory_interval == 0:
                await self._trigger_core_memory_extraction(session_id)

        except Exception as e:
            logger.error("Post-processing failed: %s", e)

    async def _trigger_daily_summary(self, session_id: str) -> None:
        """Generate and store a daily summary from recent messages."""
        try:
            messages = await self.memory.get_working_memory(session_id)
            if not messages:
                return
            messages_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in messages
            )
            summary = await self.llm.summarize_daily(messages_text)
            await self.memory.set_daily_summary(summary)
            logger.info("Daily summary updated for session %s", session_id)
        except Exception as e:
            logger.warning("Daily summary generation failed: %s", e)

    async def _trigger_core_memory_extraction(self, session_id: str) -> None:
        """Extract user preferences from recent conversation and store in core memory."""
        try:
            messages = await self.memory.get_working_memory(session_id)
            if not messages:
                return
            messages_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in messages
            )
            result = await self.llm.extract_core_preferences(messages_text)
            prefs = result.get("preferences", {})
            for key, value in prefs.items():
                if key and value:
                    await self.memory.set_core_memory(str(key), str(value))
            if prefs:
                logger.info("Core memory updated with %d preferences", len(prefs))
        except Exception as e:
            logger.warning("Core memory extraction failed: %s", e)

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
