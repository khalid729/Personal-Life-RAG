import asyncio
import base64
import gc
import hashlib
import json
import logging
from pathlib import Path

import aiofiles

from app.config import get_settings
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)

settings = get_settings()

# MIME type mappings
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
PDF_MIMES = {"application/pdf"}
AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/ogg", "audio/flac", "audio/m4a", "audio/mp4",
    "audio/x-m4a", "audio/aac",
}


class FileService:
    def __init__(self, llm: LLMService, retrieval: RetrievalService):
        self.llm = llm
        self.retrieval = retrieval
        self._whisper_lock = asyncio.Lock()

    async def process_file(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        user_context: str = "",
        tags: list[str] | None = None,
        topic: str | None = None,
    ) -> dict:
        """Route file to appropriate processor based on content type."""
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        ext = Path(filename).suffix.lower() or self._guess_ext(content_type)

        # Dedup: skip re-processing if this file was already ingested
        existing = await self.retrieval.graph.find_file_by_hash(file_hash)
        if existing:
            logger.info("File %s already processed (hash=%s…), skipping.", filename, file_hash[:12])
            return {
                "status": "duplicate",
                "filename": filename,
                "file_type": existing.get("file_type"),
                "file_hash": file_hash,
                "analysis": existing.get("properties", {}),
                "chunks_stored": 0,
                "facts_extracted": 0,
                "processing_steps": ["duplicate_skipped"],
            }

        # Save file to disk
        file_path = await self._save_file(file_bytes, file_hash, ext)
        steps = [f"saved:{file_path}"]

        if content_type in IMAGE_MIMES:
            return await self._process_image(
                file_bytes, filename, content_type, file_hash, user_context, tags, topic, steps
            )
        elif content_type in PDF_MIMES or ext == ".pdf":
            return await self._process_pdf(
                file_path, filename, file_hash, user_context, tags, topic, steps
            )
        elif content_type in AUDIO_MIMES or ext in (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"):
            return await self._process_audio(
                file_path, filename, file_hash, user_context, tags, topic, steps
            )
        else:
            return {
                "status": "error",
                "filename": filename,
                "file_hash": file_hash,
                "file_type": None,
                "analysis": {},
                "chunks_stored": 0,
                "facts_extracted": 0,
                "processing_steps": steps + ["unsupported_content_type"],
            }

    # ========================
    # IMAGE PROCESSING
    # ========================

    async def _process_image(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        file_hash: str,
        user_context: str,
        tags: list[str] | None,
        topic: str | None,
        steps: list[str],
    ) -> dict:
        # Encode to base64
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")
        steps.append("base64_encoded")

        # Classify image
        classification = await self.llm.classify_file(image_b64, content_type)
        file_type = classification.get("file_type", "info_image")
        steps.append(f"classified:{file_type}")

        # Analyze with type-specific prompt
        analysis = await self.llm.analyze_image(
            image_b64, file_type, content_type, user_context
        )
        steps.append("analyzed")

        # Convert analysis to text for ingestion
        analysis_text = self._analysis_to_text(analysis, file_type, filename)

        # Ingest through existing pipeline
        ingest_result = await self.retrieval.ingest_text(
            analysis_text,
            source_type=f"file_{file_type}",
            tags=tags,
            topic=topic,
        )
        steps.append(f"ingested:{ingest_result['chunks_stored']}chunks")

        # Store file node in graph
        await self.retrieval.graph.upsert_file_node(
            file_hash, filename, file_type, {**classification, **analysis}
        )
        steps.append("graph_node_created")

        # Auto-create expense from invoice
        auto_expense = None
        if file_type == "invoice":
            total_amount = analysis.get("total_amount", 0)
            try:
                total_amount = float(total_amount)
            except (TypeError, ValueError):
                total_amount = 0
            if total_amount > 0:
                try:
                    auto_expense = await self.retrieval.graph.create_expense_from_invoice(
                        analysis, file_hash
                    )
                    steps.append(f"auto_expense:{auto_expense.get('amount', 0)}SAR")
                except Exception as e:
                    logger.warning("Auto-expense creation failed: %s", e)
                    steps.append(f"auto_expense_error:{e}")

        # Auto-create item from inventory_item photo
        auto_item = None
        if file_type == "inventory_item":
            item_name = analysis.get("item_name", "")
            if item_name:
                try:
                    # User caption = location (e.g. "السطح > الرف الثاني")
                    location = user_context.strip() if user_context else None
                    auto_item = await self.retrieval.graph.upsert_item(
                        name=item_name,
                        brand=analysis.get("brand"),
                        description=analysis.get("description"),
                        category=analysis.get("category"),
                        condition=analysis.get("condition"),
                        quantity=analysis.get("quantity_visible", 1),
                        file_hash=file_hash,
                        location=location,
                    )
                    steps.append(f"auto_item:{item_name}")
                except Exception as e:
                    logger.warning("Auto-item creation failed: %s", e)

        # Search for similar items via vector embeddings
        similar_items = []
        if file_type == "inventory_item":
            item_desc = (analysis.get("item_name", "") + " " + analysis.get("description", "")).strip()
            if item_desc:
                try:
                    results = await self.retrieval.vector.search(
                        item_desc, limit=5, source_type="file_inventory_item"
                    )
                    current_name = analysis.get("item_name", "").lower()
                    for r in results:
                        if r["score"] >= 0.5 and current_name not in r["text"].lower()[:100]:
                            similar_items.append({
                                "text": r["text"][:200],
                                "score": round(r["score"], 2),
                            })
                    similar_items = similar_items[:3]
                except Exception as e:
                    logger.debug("Similar item search failed: %s", e)

        return {
            "status": "ok",
            "filename": filename,
            "file_type": file_type,
            "file_hash": file_hash,
            "analysis": analysis,
            "chunks_stored": ingest_result["chunks_stored"],
            "facts_extracted": ingest_result["facts_extracted"],
            "processing_steps": steps,
            "auto_expense": auto_expense,
            "auto_item": auto_item,
            "similar_items": similar_items,
        }

    # ========================
    # PDF PROCESSING
    # ========================

    async def _process_pdf(
        self,
        file_path: str,
        filename: str,
        file_hash: str,
        user_context: str,
        tags: list[str] | None,
        topic: str | None,
        steps: list[str],
    ) -> dict:
        # Extract markdown from PDF in thread pool
        loop = asyncio.get_event_loop()
        try:
            md_text = await loop.run_in_executor(
                None, self._pdf_to_markdown, file_path
            )
            steps.append(f"pdf_extracted:{len(md_text)}chars")
        except Exception as e:
            logger.error("PDF extraction failed for %s: %s", filename, e)
            return {
                "status": "error",
                "filename": filename,
                "file_type": "pdf_document",
                "file_hash": file_hash,
                "analysis": {"error": str(e)},
                "chunks_stored": 0,
                "facts_extracted": 0,
                "processing_steps": steps + [f"pdf_error:{e}"],
            }

        if not md_text.strip():
            return {
                "status": "error",
                "filename": filename,
                "file_type": "pdf_document",
                "file_hash": file_hash,
                "analysis": {"error": "No text extracted from PDF"},
                "chunks_stored": 0,
                "facts_extracted": 0,
                "processing_steps": steps + ["pdf_empty"],
            }

        # Prepend context if provided
        if user_context:
            md_text = f"[User context: {user_context}]\n\n{md_text}"

        # Ingest through existing pipeline
        ingest_result = await self.retrieval.ingest_text(
            md_text,
            source_type="file_pdf_document",
            tags=tags,
            topic=topic,
        )
        steps.append(f"ingested:{ingest_result['chunks_stored']}chunks")

        # Store file node in graph
        await self.retrieval.graph.upsert_file_node(
            file_hash, filename, "pdf_document",
            {"brief_description": f"PDF document: {filename}", "pages": md_text[:200]},
        )
        steps.append("graph_node_created")

        return {
            "status": "ok",
            "filename": filename,
            "file_type": "pdf_document",
            "file_hash": file_hash,
            "analysis": {"text_length": len(md_text), "preview": md_text[:500]},
            "chunks_stored": ingest_result["chunks_stored"],
            "facts_extracted": ingest_result["facts_extracted"],
            "processing_steps": steps,
        }

    def _pdf_to_markdown(self, file_path: str) -> str:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(file_path)

    # ========================
    # AUDIO PROCESSING
    # ========================

    async def _process_audio(
        self,
        file_path: str,
        filename: str,
        file_hash: str,
        user_context: str,
        tags: list[str] | None,
        topic: str | None,
        steps: list[str],
    ) -> dict:
        # Transcribe with WhisperX (serialized via lock, on-demand load)
        async with self._whisper_lock:
            loop = asyncio.get_event_loop()
            try:
                transcript = await loop.run_in_executor(
                    None, self._transcribe_audio, file_path
                )
                steps.append(f"transcribed:{len(transcript)}chars")
            except Exception as e:
                logger.error("Audio transcription failed for %s: %s", filename, e)
                return {
                    "status": "error",
                    "filename": filename,
                    "file_type": "audio_recording",
                    "file_hash": file_hash,
                    "analysis": {"error": str(e)},
                    "chunks_stored": 0,
                    "facts_extracted": 0,
                    "processing_steps": steps + [f"audio_error:{e}"],
                }

        if not transcript.strip():
            return {
                "status": "error",
                "filename": filename,
                "file_type": "audio_recording",
                "file_hash": file_hash,
                "analysis": {"error": "No speech detected in audio"},
                "chunks_stored": 0,
                "facts_extracted": 0,
                "processing_steps": steps + ["audio_empty"],
            }

        # Prepend context if provided
        if user_context:
            transcript = f"[User context: {user_context}]\n\n{transcript}"

        # Transcription only — no ingest/fact extraction here.
        # The caller (e.g. Telegram bot) sends the transcript to /chat/
        # which handles storage and fact extraction via post_process.
        steps.append("transcription_only")

        return {
            "status": "ok",
            "filename": filename,
            "file_type": "audio_recording",
            "file_hash": file_hash,
            "analysis": {"text_length": len(transcript), "preview": transcript},
            "chunks_stored": 0,
            "facts_extracted": 0,
            "processing_steps": steps,
        }

    def _transcribe_audio(self, file_path: str) -> str:
        """Load WhisperX on-demand, transcribe, then release GPU memory."""
        import torch
        import whisperx

        # PyTorch 2.6+ treats weights_only=None as True. Lightning passes
        # None explicitly, so we wrap torch.load to convert None→False.
        _orig_torch_load = torch.load.__wrapped__ if hasattr(torch.load, "__wrapped__") else torch.load
        def _patched_load(*a, **kw):
            if kw.get("weights_only") is None:
                kw["weights_only"] = False
            return _orig_torch_load(*a, **kw)
        _patched_load.__wrapped__ = _orig_torch_load
        torch.load = _patched_load

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = None
        audio = None
        try:
            # Load model
            model = whisperx.load_model(
                settings.whisperx_model,
                device=device,
                compute_type=settings.whisperx_compute_type,
                language=settings.whisperx_language,
            )

            # Load and transcribe audio
            audio = whisperx.load_audio(file_path)
            result = model.transcribe(
                audio, batch_size=settings.whisperx_batch_size
            )

            # Build transcript text
            segments = result.get("segments", [])
            transcript = " ".join(seg.get("text", "") for seg in segments).strip()

            return transcript
        finally:
            # Restore original torch.load
            torch.load = _orig_torch_load
            # Release GPU memory
            if model is not None:
                del model
            if audio is not None:
                del audio
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("WhisperX model released, GPU memory freed")

    # ========================
    # HELPERS
    # ========================

    async def _save_file(self, file_bytes: bytes, file_hash: str, ext: str) -> str:
        """Save file to data/files/{hash[:2]}/{hash}.{ext}"""
        subdir = Path(settings.file_storage_path) / file_hash[:2]
        subdir.mkdir(parents=True, exist_ok=True)
        file_path = subdir / f"{file_hash}{ext}"
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_bytes)
        return str(file_path)

    def _analysis_to_text(self, analysis: dict, file_type: str, filename: str) -> str:
        """Convert structured analysis JSON to readable text for ingestion."""
        parts = [f"File: {filename} (type: {file_type})"]

        if file_type == "invoice":
            vendor = analysis.get("vendor", "Unknown")
            total = analysis.get("total_amount", "N/A")
            currency = analysis.get("currency", "SAR")
            date = analysis.get("date", "N/A")
            parts.append(f"Invoice from {vendor}, date: {date}, total: {total} {currency}")
            items = analysis.get("items", [])
            if items:
                parts.append("Items:")
                for item in items:
                    parts.append(f"  - {item.get('name', '?')}: {item.get('price', '?')} {currency}")
        elif file_type == "business_card":
            name = analysis.get("name", "Unknown")
            company = analysis.get("company", "")
            title = analysis.get("title", "")
            phone = analysis.get("phone", "")
            email = analysis.get("email", "")
            parts.append(f"Business card: {name}, {title} at {company}")
            if phone:
                parts.append(f"Phone: {phone}")
            if email:
                parts.append(f"Email: {email}")
        elif file_type == "personal_photo":
            desc = analysis.get("description", "")
            tags = analysis.get("tags", [])
            parts.append(f"Photo description: {desc}")
            if tags:
                parts.append(f"Tags: {', '.join(tags)}")
        elif file_type == "inventory_item":
            item_name = analysis.get("item_name", "")
            brand = analysis.get("brand", "")
            category = analysis.get("category", "")
            condition = analysis.get("condition", "")
            desc = analysis.get("description", "")
            qty = analysis.get("quantity_visible", 1)
            parts.append(f"Inventory item: {item_name}")
            if brand:
                parts.append(f"Brand: {brand}")
            if category:
                parts.append(f"Category: {category}")
            if condition:
                parts.append(f"Condition: {condition}")
            if qty and qty > 1:
                parts.append(f"Quantity: {qty}")
            if desc:
                parts.append(f"Description: {desc}")
            specs = analysis.get("specifications", [])
            if specs:
                parts.append(f"Specs: {', '.join(str(s) for s in specs)}")
        elif file_type == "official_document":
            doc_type = analysis.get("document_type", "")
            title = analysis.get("title", "")
            summary = analysis.get("summary", "")
            parts.append(f"Document type: {doc_type}, title: {title}")
            if summary:
                parts.append(f"Summary: {summary}")
        else:
            # Generic: dump all values as text
            for k, v in analysis.items():
                if v and k not in ("error", "raw"):
                    if isinstance(v, list):
                        parts.append(f"{k}: {', '.join(str(i) for i in v)}")
                    else:
                        parts.append(f"{k}: {v}")

        return "\n".join(parts)

    def _guess_ext(self, content_type: str) -> str:
        mime_to_ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "application/pdf": ".pdf",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/ogg": ".ogg",
            "audio/flac": ".flac",
            "audio/m4a": ".m4a",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
            "audio/aac": ".aac",
        }
        return mime_to_ext.get(content_type, ".bin")
