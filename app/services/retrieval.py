import asyncio
import logging
import re
from datetime import datetime

import tiktoken

from app.config import get_settings
from app.prompts.conversation import (
    SIDE_EFFECT_ROUTES,
    NUMBER_SELECTION,
    build_confirmation_message,
    is_action_intent,
    is_confirmation,
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

DAILY_PLAN_KEYWORDS = re.compile(
    r"(رتب.*يومي|خطة اليوم|خطط.*يومي|يومي ايش|plan my day|daily plan|today.?s plan|what.?s on)",
    re.IGNORECASE,
)

KNOWLEDGE_KEYWORDS = re.compile(
    r"(معلومة|احفظ.?لي|أعرف عن|اعرف عن|وش أعرف|knowledge|what do I know|info about)",
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

INVENTORY_MOVE_KEYWORDS = re.compile(
    r"(نقلت|حركت|حطيته في|حطيتها في|شلته من|نقله|حوّل|moved|relocated|transferred|put it in)",
    re.IGNORECASE,
)

INVENTORY_USAGE_KEYWORDS = re.compile(
    r"(استخدمت|ضاع|خلص|عطيت|انكسر|رميت|used .+ (cable|item|tool|بطارية|كيبل)|gave away|lost|broke)",
    re.IGNORECASE,
)

INVENTORY_KEYWORDS = re.compile(
    r"(مخزون|جرد|أغراضي|حوائجي|وين ال|فين ال|عندي |inventory|items|stock|where is|do i have|how many .+ do i)",
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

    # Daily plan + Knowledge
    if DAILY_PLAN_KEYWORDS.search(text):
        return "graph_daily_plan"
    if KNOWLEDGE_KEYWORDS.search(text):
        return "graph_knowledge"

    if PROJECT_KEYWORDS.search(text):
        return "graph_project"
    if PERSON_KEYWORDS.search(text):
        return "graph_person"
    if TASK_KEYWORDS.search(text):
        return "graph_task"
    if INVENTORY_MOVE_KEYWORDS.search(text):
        return "graph_inventory"
    if INVENTORY_USAGE_KEYWORDS.search(text):
        return "graph_inventory"
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
        """Agentic RAG pipeline with confirmation flow + multi-turn history.

        Pre-check: handle pending confirmations (yes/no/number selection)
        1. Translate query Arabic → English
        2. FAST PATH: keyword router — if match, skip Think step
        3. Confirmation gate: if side-effect route + action intent, confirm first
        4. THINK (if no keyword match): LLM decides strategy + search queries
        5. ACT: execute retrieval strategy → context_parts, sources
        6. REFLECT + Self-RAG: LLM scores chunks, filter below threshold
        7. RETRY (if !sufficient && retries > 0): flip strategy, merge results
        8. Build context (system memory + conversation turns + filtered chunks, ≤15K tokens)
        9. Generate Arabic response with multi-turn history
        10. Return reply + sources + route + agentic_trace
        """
        agentic_trace: list[dict] = []

        # --- A. Confirmation pre-check ---
        if settings.confirmation_enabled:
            pending = await self.memory.get_pending_action(session_id)
            if pending:
                confirmation = is_confirmation(query_ar.strip())
                if confirmation == "yes":
                    result = await self._execute_confirmed_action(pending, session_id)
                    # Don't clear if disambiguation was set (pending re-stored)
                    if not pending.get("disambiguation_options"):
                        await self.memory.clear_pending_action(session_id)
                    return {
                        "reply": result,
                        "sources": [],
                        "route": pending.get("route", ""),
                        "query_en": pending.get("query_en", ""),
                        "agentic_trace": [{"step": "confirmed_action", "action_type": pending.get("action_type")}],
                        "pending_confirmation": bool(pending.get("disambiguation_options")),
                    }
                elif confirmation == "no":
                    await self.memory.clear_pending_action(session_id)
                    return {
                        "reply": "تمام، ما سويت شي.",
                        "sources": [],
                        "route": pending.get("route", ""),
                        "query_en": "",
                        "agentic_trace": [{"step": "cancelled_action"}],
                    }
                elif NUMBER_SELECTION.match(query_ar.strip()):
                    result = await self._resolve_disambiguation(pending, int(query_ar.strip()))
                    await self.memory.clear_pending_action(session_id)
                    return {
                        "reply": result,
                        "sources": [],
                        "route": pending.get("route", ""),
                        "query_en": pending.get("query_en", ""),
                        "agentic_trace": [{"step": "disambiguation_resolved"}],
                    }
                else:
                    # Not a confirmation — clear stale pending and proceed normally
                    await self.memory.clear_pending_action(session_id)

        # Step 1: Translate
        query_en = await self.llm.translate_to_english(query_ar)

        # Step 2: Fast path — keyword router
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

        # --- B. Confirmation creation (side-effect routes only) ---
        if (
            settings.confirmation_enabled
            and route in SIDE_EFFECT_ROUTES
            and is_action_intent(query_ar, route)
        ):
            # Extract facts to understand the action
            facts = await self.llm.extract_facts(query_en)
            entities = facts.get("entities", [])
            action_type = self._classify_action_type(entities, route)

            if action_type:
                # Check clarification — does the message have enough info?
                # Skip if extraction already found named entities (extraction success = sufficient info)
                if entities and entities[0].get("entity_name"):
                    clarification = {"complete": True, "missing_fields": []}
                else:
                    clarification = await self.llm.check_clarification(query_en, action_type)
                if not clarification.get("complete", True) or not entities:
                    # Missing info — ask for it (no pending stored)
                    question = clarification.get("clarification_question_ar", "ممكن توضح أكثر؟")
                    return {
                        "reply": question,
                        "sources": [],
                        "route": route,
                        "query_en": query_en,
                        "agentic_trace": [{"step": "clarification", "missing": clarification.get("missing_fields", [])}],
                    }

                # Build confirmation message and store pending action
                confirm_msg = build_confirmation_message(action_type, entities)
                pending_action = {
                    "action_type": action_type,
                    "extracted_entities": entities,
                    "query_ar": query_ar,
                    "query_en": query_en,
                    "route": route,
                    "created_at": datetime.utcnow().isoformat(),
                    "confirmation_message": confirm_msg,
                }
                await self.memory.set_pending_action(session_id, pending_action)
                agentic_trace.append({"step": "confirmation_requested", "action_type": action_type})
                return {
                    "reply": confirm_msg,
                    "sources": [],
                    "route": route,
                    "query_en": query_en,
                    "agentic_trace": agentic_trace,
                    "pending_confirmation": True,
                }

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

            threshold = settings.self_rag_threshold
            if chunk_scores:
                scored_parts = []
                for cs in chunk_scores:
                    idx = cs.get("index", -1)
                    score = cs.get("score", 1.0)
                    if 0 <= idx < len(context_parts) and score >= threshold:
                        scored_parts.append(context_parts[idx])
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

        # --- C. Multi-turn history in response generation ---
        memory_context = await self.memory.build_system_memory_context(session_id)
        conversation_history = await self.memory.get_conversation_turns(session_id)
        retrieved_context = "\n\n".join(filtered_parts)

        # Token budget: system memory + history + retrieved context ≤ max
        memory_tokens = count_tokens(memory_context)
        history_tokens = sum(count_tokens(t.get("content", "")) for t in conversation_history)
        remaining = self.max_context_tokens - memory_tokens - history_tokens
        if remaining < 0:
            remaining = 500  # Minimum for retrieved context
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

        # Step 8: Generate response with multi-turn history
        reply = await self.llm.generate_response(
            query_ar, retrieved_context, memory_context,
            conversation_history=conversation_history,
        )

        return {
            "reply": reply,
            "sources": list(set(sources)),
            "route": route,
            "query_en": query_en,
            "agentic_trace": agentic_trace,
        }

    def _classify_action_type(self, entities: list[dict], route: str) -> str | None:
        """Map extracted entity types to action type string."""
        for entity in entities:
            etype = entity.get("entity_type", "")
            if etype in ("Expense", "Debt", "DebtPayment", "Reminder", "Item", "ItemUsage", "ItemMove"):
                return etype
        # Fallback from route
        route_map = {
            "graph_financial": "Expense",
            "graph_debt_payment": "DebtPayment",
            "graph_reminder": "Reminder",
            "graph_reminder_action": "Reminder",
            "graph_inventory": "Item",
        }
        return route_map.get(route)

    async def _execute_confirmed_action(self, pending: dict, session_id: str) -> str:
        """Execute a previously confirmed action."""
        entities = pending.get("extracted_entities", [])
        action_type = pending.get("action_type", "")

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
            return await self.graph.search_nodes(query_en, limit=5)
        elif route == "graph_task":
            return await self.graph.query_active_tasks()
        elif route == "graph_inventory":
            return await self.graph.query_inventory(query_en)
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
            "graph_daily_plan", "graph_knowledge",
            "graph_project", "graph_person", "graph_task",
            "graph_inventory",
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
        self,
        query_ar: str,
        reply_ar: str,
        session_id: str,
        skip_fact_extraction: bool = False,
    ) -> None:
        """Run after response is sent: update memory, extract facts, store embeddings."""
        try:
            # Update working memory
            await self.memory.push_message(session_id, "user", query_ar)
            await self.memory.push_message(session_id, "assistant", reply_ar)

            # Increment message counter for periodic tasks
            msg_count = await self.memory.increment_message_count(session_id)

            if not skip_fact_extraction:
                # Translate user query separately for fact extraction
                # (combined translation often loses actionable intent)
                query_en = await self.llm.translate_to_english(query_ar)

                # Extract facts from user query alone (captures intents like
                # reminders, expenses, debts that get lost in combined translation)
                query_facts = await self.llm.extract_facts(query_en)
                if query_facts.get("entities"):
                    await self.graph.upsert_from_facts(query_facts)

                # Also extract from combined exchange for relationship context,
                # but skip DebtPayment to avoid double-applying payments
                query_entity_types = {
                    e.get("entity_type") for e in query_facts.get("entities", [])
                }
                combined = f"User said: {query_ar}\nAssistant replied: {reply_ar}"
                combined_en = await self.llm.translate_to_english(combined)
                combined_facts = await self.llm.extract_facts(combined_en)
                if combined_facts.get("entities"):
                    combined_facts["entities"] = [
                        e for e in combined_facts["entities"]
                        if e.get("entity_type") not in query_entity_types
                    ]
                    if combined_facts["entities"]:
                        await self.graph.upsert_from_facts(combined_facts)

                # Store the exchange as a vector for future retrieval
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
