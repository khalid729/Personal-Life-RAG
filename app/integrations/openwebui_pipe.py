"""
Open WebUI Pipe for Personal Life RAG — Tool-Calling Architecture.
Version: 2.0

Uses /chat/v2 (tool-calling endpoint): LLM picks tools → code executes → real results → LLM responds.
The model cannot lie because it sees actual tool outcomes before generating its response.

Copy this file's content into Open WebUI Admin → Functions → Add Function (type: Pipe).
Select "Personal RAG" model in the Open WebUI sidebar to use this pipe.

The existing Filter + Tools setup remains for users who select the regular Qwen3-VL model.
"""

import json
import os
import re
import base64
import requests
from typing import Generator, Union
from pydantic import BaseModel, Field


class Pipe:
    """Personal Life RAG Pipe v2.1 — Tool-calling with JSON guard + internal prompt filter."""

    VERSION = "2.1"

    class Valves(BaseModel):
        api_url: str = Field(
            default="http://host.docker.internal:8500",
            description="Personal Life RAG API URL",
        )
        owui_base_url: str = Field(
            default="http://localhost:8080",
            description="Open WebUI base URL (for fetching full file content)",
        )
        owui_api_key: str = Field(
            default="",
            description="Open WebUI API key (needed for full file extraction)",
        )
        session_id: str = Field(
            default="openwebui",
            description="Session ID for conversation continuity",
        )
        auto_process_files: bool = Field(
            default=True,
            description="Automatically process uploaded files via /ingest/file",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._ingested_files: set = set()  # track already-ingested file IDs

    # ========================
    # ENTRY POINT
    # ========================

    # Open WebUI internal prompt prefixes — must NOT be forwarded to RAG API
    # NOTE: "### Task:" removed — Open WebUI also uses it for file-attached messages.
    # Internal tasks are caught by _INTERNAL_KEYWORDS instead.
    _INTERNAL_PREFIXES = (
        "### Instructions:",
        "Create a concise",
        "Generate a concise",
        "Generate 1-3 broad tags",
    )

    # Open WebUI internal keywords (anywhere in text)
    _INTERNAL_KEYWORDS = (
        "ONLY respond with the title",
        "ONLY respond with a short",
        "conversation title",
        "Generate a succinct",
        "Create a concise title",
        "Generate 1-3 broad tags",
    )

    def pipe(self, body: dict, __user__: dict = {}, __metadata__: dict = {}, __files__: list = None) -> Union[str, Generator]:
        import sys

        messages = body.get("messages", [])
        if not messages:
            return ""

        last_msg = messages[-1] if messages else {}
        user_text = self._extract_text(last_msg.get("content", ""))

        if not user_text.strip():
            return ""

        # Skip Open WebUI internal prompts (title/tag generation)
        stripped = user_text.strip()
        if any(stripped.startswith(p) for p in self._INTERNAL_PREFIXES):
            return ""
        if any(kw in stripped for kw in self._INTERNAL_KEYWORDS):
            return ""

        # Also skip if system prompt looks like internal task
        sys_msgs = [m.get("content", "") for m in messages if m.get("role") == "system"]
        for s in sys_msgs:
            if any(kw in s for kw in self._INTERNAL_KEYWORDS):
                return ""
            if any(s.strip().startswith(p) for p in self._INTERNAL_PREFIXES):
                return ""

        # Process files if any
        owui_files = __files__ or []
        meta_files = (__metadata__ or {}).get("files", []) or []
        has_files = self.valves.auto_process_files and (len(meta_files) > 0 or len(owui_files) > 0)

        # Use Open WebUI chat_id so each conversation gets fresh working memory
        session_id = (
            (__metadata__ or {}).get("chat_id")
            or body.get("chat_id")
            or self.valves.session_id
        )
        stream = body.get("stream", False)

        if has_files and stream:
            # Stream mode with files: yield progress while processing, then stream chat
            return self._stream_with_files(
                body, last_msg, user_text, owui_files, __metadata__, __user__,
                session_id,
            )

        if has_files:
            # Strip OWUI RAG injection BEFORE file processing
            clean_text = self._strip_owui_rag_context(user_text)
            file_context = self._process_files(
                body, last_msg, clean_text, owui_files, __metadata__, __user__
            )
            user_text = (clean_text + "\n\n" + file_context) if file_context else clean_text

        payload = {"message": user_text, "session_id": session_id}

        if stream:
            return self._stream(payload)
        else:
            return self._sync(payload)

    # ========================
    # STREAMING
    # ========================

    def _stream_with_files(
        self, body, last_msg, user_text, owui_files, metadata, user, session_id,
    ) -> Generator:
        """Process files while yielding progress tokens, then stream chat response."""
        import sys

        yield "جاري معالجة الملف"

        clean_text = self._strip_owui_rag_context(user_text)
        file_context = self._process_files(
            body, last_msg, clean_text, owui_files, metadata, user
        )

        final_text = (clean_text + "\n\n" + file_context) if file_context else clean_text
        payload = {"message": final_text, "session_id": session_id}

        yield "...\n\n"

        # Now stream the chat response
        url = self.valves.api_url.rstrip("/")
        try:
            with requests.post(
                f"{url}/chat/v2/stream",
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                if resp.status_code != 200:
                    yield f"\n\nخطأ: HTTP {resp.status_code}"
                    return

                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        import json
                        event = json.loads(line)
                        etype = event.get("type", "")
                        if etype == "token":
                            yield event.get("content", "")
                        elif etype == "done":
                            break
                    except Exception:
                        continue
        except Exception as e:
            print(f"[PIPE] stream error: {e}", file=sys.stderr)
            yield f"\n\nخطأ في الاتصال: {str(e)}"

    def _stream(self, payload: dict) -> Generator:
        url = self.valves.api_url.rstrip("/")
        try:
            with requests.post(
                f"{url}/chat/v2/stream",
                json=payload,
                stream=True,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                first_chunk = True
                buffer = ""
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "token":
                        content = data.get("content", "")
                        if first_chunk:
                            buffer += content
                            # Wait until we have enough to detect JSON
                            if len(buffer.lstrip()) < 2:
                                continue
                            first_chunk = False
                            stripped = buffer.lstrip()
                            if stripped.startswith("{") or stripped.startswith("["):
                                # JSON detected — accumulate rest and convert
                                remaining = self._collect_remaining(resp)
                                full = buffer + remaining
                                yield self._handle_json_fallback(full)
                                return
                            else:
                                yield buffer
                        else:
                            yield content
                    elif data.get("type") == "done":
                        # Flush any buffered content that never reached 2 chars
                        if first_chunk and buffer:
                            yield buffer
                        break
        except requests.exceptions.ConnectionError:
            yield "خطأ: لا يمكن الاتصال بالـ API. تأكد من تشغيل الخادم."
        except requests.exceptions.Timeout:
            yield "خطأ: انتهت مهلة الاتصال."
        except Exception as e:
            yield f"خطأ: {str(e)}"

    def _collect_remaining(self, resp) -> str:
        """Collect all remaining tokens from an active stream."""
        parts = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "token":
                parts.append(data.get("content", ""))
            elif data.get("type") == "done":
                break
        return "".join(parts)

    def _handle_json_fallback(self, text: str) -> str:
        """Convert malformed JSON response to natural Arabic text."""
        try:
            obj = json.loads(text.strip())
            # Extract list items from common patterns (follow_ups, items, suggestions)
            items = None
            if isinstance(obj, dict):
                for key in ("follow_ups", "items", "suggestions", "tasks", "results"):
                    if key in obj and isinstance(obj[key], list):
                        items = obj[key]
                        break
                if items is None:
                    # Try first list value in the dict
                    for v in obj.values():
                        if isinstance(v, list):
                            items = v
                            break
            elif isinstance(obj, list):
                items = obj

            if items:
                lines = []
                for item in items:
                    if isinstance(item, str):
                        lines.append(f"• {item}")
                    elif isinstance(item, dict):
                        # Try common text fields
                        txt = item.get("text") or item.get("title") or item.get("name") or str(item)
                        lines.append(f"• {txt}")
                return "\n".join(lines)
        except (json.JSONDecodeError, ValueError):
            pass

        # Could not parse — ask user to rephrase
        return "عذراً، حصل خطأ في صياغة الرد. ممكن تعيد صياغة سؤالك؟"

    # ========================
    # SYNC FALLBACK
    # ========================

    def _sync(self, payload: dict) -> str:
        url = self.valves.api_url.rstrip("/")
        try:
            resp = requests.post(f"{url}/chat/v2", json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("reply", "لا توجد إجابة.")
        except requests.exceptions.ConnectionError:
            return "خطأ: لا يمكن الاتصال بالـ API. تأكد من تشغيل الخادم."
        except requests.exceptions.Timeout:
            return "خطأ: انتهت مهلة الاتصال."
        except Exception as e:
            return f"خطأ: {str(e)}"

    # ========================
    # FILE PROCESSING
    # ========================

    def _process_files(
        self, body: dict, last_msg: dict, user_text: str,
        owui_files: list = None, metadata: dict = None, user: dict = None,
    ) -> str:
        """Detect and process files, return formatted result string."""
        import sys
        files = []

        # Source 1: metadata.files — Open WebUI passes file IDs here for Pipes
        meta_files = (metadata or {}).get("files", []) or []
        for f in meta_files:
            if not isinstance(f, dict):
                continue
            file_id = f.get("id", "")
            filename = f.get("name", f.get("filename", "unknown"))
            if not file_id:
                continue
            # Skip already-ingested files
            if file_id in self._ingested_files:
                print(f"[PIPE] skipping {filename} — already ingested", file=sys.stderr)
                continue
            # Try to get Docker path directly (preferred — raw file)
            file_path = self._get_owui_file_path(file_id)
            if file_path:
                print(f"[PIPE] using Docker path for {filename}: {file_path}", file=sys.stderr)
                files.append({
                    "path": file_path,
                    "data": "",
                    "filename": filename,
                    "content_type": f.get("type", f.get("content_type", "")),
                    "file_id": file_id,
                })
            else:
                # Fallback: read content via OWUI API
                content = self._fetch_owui_file_content(file_id, user)
                if content:
                    print(f"[PIPE] fetched {filename} via content: {len(content)} chars", file=sys.stderr)
                    files.append({
                        "path": "",
                        "data": content,
                        "filename": filename,
                        "content_type": f.get("type", f.get("content_type", "")),
                        "file_id": file_id,
                    })

        # Source 2: __files__ parameter (primary source for filters)
        for f in (owui_files or []):
            meta = f.get("meta", {})
            data = f.get("data", {})
            path = meta.get("path", "") or f.get("path", "")
            content_data = ""
            if isinstance(data, dict):
                content_data = data.get("content", "")
            elif isinstance(data, str):
                content_data = data
            files.append({
                "path": path,
                "data": content_data,
                "filename": f.get("filename", meta.get("name", "unknown")),
                "content_type": meta.get("content_type", f.get("type", "")),
            })

        # Message-level files
        for f in last_msg.get("files", []):
            file_obj = f.get("file", {})
            files.append({
                "path": file_obj.get("path", "") or f.get("path", ""),
                "data": f.get("data", ""),
                "filename": f.get("name", file_obj.get("filename", "unknown")),
                "content_type": f.get("content_type", f.get("type", "")),
            })

        # Body-level files
        for f in body.get("files", []):
            file_obj = f.get("file", {})
            files.append({
                "path": file_obj.get("path", "") or f.get("path", ""),
                "data": f.get("data", ""),
                "filename": f.get("name", file_obj.get("filename", "unknown")),
                "content_type": f.get("content_type", f.get("type", "")),
            })

        # Multimodal content — base64 data URLs
        content = last_msg.get("content", "")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        files.append({
                            "data": url,
                            "filename": "uploaded_image",
                            "content_type": "",
                            "path": "",
                        })

        if not files:
            return ""

        results = []
        for f in files:
            result = self._send_file(f, user_text)
            if result:
                results.append(result)
                # Mark file as ingested so we don't re-process on next message
                fid = f.get("file_id", "")
                if fid:
                    self._ingested_files.add(fid)

        return "\n".join(results) if results else ""

    def _send_file(self, file_info: dict, user_text: str) -> str:
        """Send a single file to /ingest/file or /ingest/text, return formatted result."""
        url = self.valves.api_url.rstrip("/")
        file_data = file_info.get("data", "")
        file_path = file_info.get("path", "")
        filename = file_info.get("filename", "unknown")

        try:
            # Base64 data URL
            if file_data and isinstance(file_data, str) and file_data.startswith("data:"):
                header, encoded = file_data.split(",", 1)
                file_bytes = base64.b64decode(encoded)
                mime_match = re.match(r"data:([^;]+)", header)
                mime_type = mime_match.group(1) if mime_match else "application/octet-stream"
                ext_map = {
                    "image/jpeg": ".jpg", "image/png": ".png",
                    "image/gif": ".gif", "image/webp": ".webp",
                    "application/pdf": ".pdf",
                    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/mp4": ".m4a",
                }
                ext = ext_map.get(mime_type, ".bin")
                upload_name = filename if filename != "uploaded_image" else f"upload{ext}"
                resp = requests.post(
                    f"{url}/ingest/file",
                    files={"file": (upload_name, file_bytes, mime_type)},
                    data={"context": user_text},
                    timeout=180,
                )

            # File path (Docker path)
            elif file_path and os.path.exists(file_path):
                upload_name = filename if filename != "unknown" else os.path.basename(file_path)
                ext = os.path.splitext(file_path)[1].lower()
                ct_map = {
                    ".pdf": "application/pdf",
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".gif": "image/gif",
                    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
                    ".md": "text/markdown", ".markdown": "text/markdown",
                    ".txt": "text/plain", ".text": "text/plain",
                    ".csv": "text/plain", ".log": "text/plain",
                    ".json": "application/json", ".xml": "application/xml",
                    ".yaml": "text/plain", ".yml": "text/plain",
                    ".py": "text/plain", ".js": "text/plain", ".ts": "text/plain",
                }
                content_type = ct_map.get(ext, "application/octet-stream")
                with open(file_path, "rb") as f:
                    resp = requests.post(
                        f"{url}/ingest/file",
                        files={"file": (upload_name, f, content_type)},
                        data={"context": user_text},
                        timeout=180,
                    )

            # Plain text content (Open WebUI extracts text from .md/.txt etc.)
            elif file_data and isinstance(file_data, str) and len(file_data.strip()) > 0:
                ext = os.path.splitext(filename)[1].lower()
                ct_text_map = {
                    ".md": "text/markdown", ".markdown": "text/markdown",
                    ".txt": "text/plain", ".text": "text/plain",
                    ".csv": "text/plain", ".log": "text/plain",
                    ".json": "text/plain", ".yaml": "text/plain",
                    ".yml": "text/plain", ".xml": "text/plain",
                    ".html": "text/plain", ".htm": "text/plain",
                    ".rst": "text/plain",
                }
                content_type = ct_text_map.get(ext, "application/octet-stream")
                file_bytes = file_data.encode("utf-8")
                resp = requests.post(
                    f"{url}/ingest/file",
                    files={"file": (filename, file_bytes, content_type)},
                    data={"context": user_text},
                    timeout=180,
                )
            else:
                return ""

            if resp.status_code != 200:
                return f"خطأ في معالجة الملف: HTTP {resp.status_code}"
            return self._format_file_result(resp.json())

        except Exception as e:
            return f"خطأ في معالجة الملف: {str(e)}"

    def _format_file_result(self, result: dict) -> str:
        """Format /ingest/file response for injection into user message."""
        status = result.get("status", "unknown")
        if status == "error":
            return f"خطأ: {result.get('error', 'فشل المعالجة')}"
        if status == "duplicate":
            return f"الملف موجود مسبقاً: {result.get('filename', '')}"

        parts = []
        chunks = result.get("chunks_stored", 0)
        facts = result.get("facts_extracted", 0)
        if chunks > 0 or facts > 0:
            parts.append(f"تم تخزين {chunks} جزء واستخراج {facts} حقيقة")

        entities = result.get("entities", [])
        if entities:
            parts.append("المعلومات المستخرجة:")
            for ent in entities:
                ent_type = ent.get("entity_type", "")
                ent_name = ent.get("entity_name", "")
                desc = ent.get("properties", {}).get("description", "")
                line = f"  - [{ent_type}] {ent_name}"
                if desc:
                    line += f": {desc[:100]}"
                parts.append(line)

        if not parts:
            preview = result.get("analysis", {}).get("preview", "")
            if preview:
                parts.append(f"معاينة: {preview[:300]}")

        return "\n".join(parts) if parts else f"تمت المعالجة ({status})"

    # ========================
    # OPEN WEBUI FILE API
    # ========================

    def _get_owui_file_path(self, file_id: str) -> str:
        """Get Docker filesystem path for an OWUI file (without reading content)."""
        import sys
        try:
            from open_webui.models.files import Files
            file_obj = Files.get_file_by_id(file_id)
            if file_obj:
                meta = file_obj.meta or {}
                # Check meta.path first (some OWUI versions store it)
                path = meta.get("path", "")
                if path and os.path.exists(path):
                    return path
                # Build path from OWUI convention: /app/backend/data/uploads/{id}_{filename}
                filename = file_obj.filename or meta.get("name", "")
                if filename:
                    built_path = f"/app/backend/data/uploads/{file_id}_{filename}"
                    if os.path.exists(built_path):
                        print(f"[PIPE] built path: {built_path}", file=sys.stderr)
                        return built_path
        except ImportError:
            pass
        except Exception as e:
            print(f"[PIPE] _get_owui_file_path error: {e}", file=sys.stderr)
        return ""

    def _fetch_owui_file_content(self, file_id: str, user: dict = None) -> str:
        """Fetch full file content from Open WebUI.

        Strategy 1: Direct import (pipe runs inside OWUI process — no auth needed)
        Strategy 2: HTTP API fallback (needs owui_api_key valve)
        """
        import sys

        # Strategy 1: Direct import from Open WebUI internals (preferred)
        try:
            from open_webui.models.files import Files
            file_obj = Files.get_file_by_id(file_id)
            if file_obj:
                # Prefer raw file from path (OWUI's data.content may be queries/summaries)
                meta = file_obj.meta or {}
                path = meta.get("path", "")
                # Build path from OWUI convention if meta.path is empty
                if not path:
                    filename = file_obj.filename or meta.get("name", "")
                    if filename:
                        path = f"/app/backend/data/uploads/{file_id}_{filename}"
                if path and os.path.exists(path):
                    try:
                        with open(path, "rb") as f:
                            raw = f.read()
                        # Try UTF-8 first, fall back to latin-1
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            text = raw.decode("latin-1")
                        if text and len(text.strip()) > 10:
                            print(f"[PIPE] got file from path {path}: {len(text)} chars", file=sys.stderr)
                            return text
                    except Exception as e:
                        print(f"[PIPE] path read failed: {e}", file=sys.stderr)
                # Fallback: extracted text content
                file_data = file_obj.data or {}
                if isinstance(file_data, dict):
                    content = file_data.get("content", "")
                    if content and len(content.strip()) > 10:
                        print(f"[PIPE] got file via data.content: {len(content)} chars", file=sys.stderr)
                        return content
        except ImportError:
            print("[PIPE] open_webui.models.files not available, trying HTTP", file=sys.stderr)
        except Exception as e:
            print(f"[PIPE] direct import error: {e}", file=sys.stderr)

        # Strategy 2: HTTP API fallback
        base_url = self.valves.owui_base_url.rstrip("/")
        api_key = self.valves.owui_api_key
        if not api_key:
            print("[PIPE] no OWUI API key — cannot fetch file via HTTP", file=sys.stderr)
            return ""

        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = requests.get(
                f"{base_url}/api/v1/files/{file_id}",
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                file_data = data.get("data", {})
                if isinstance(file_data, dict):
                    content = file_data.get("content", "")
                    if content and len(content.strip()) > 10:
                        return content

            resp = requests.get(
                f"{base_url}/api/v1/files/{file_id}/content",
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200 and len(resp.text.strip()) > 10:
                return resp.text
        except Exception as e:
            print(f"[PIPE] HTTP fallback error: {e}", file=sys.stderr)

        return ""

    # Regex to detect OWUI RAG injection: "### Task: ... ### Context: ... ### Query: ..."
    _RAG_QUERY_RE = re.compile(
        r"###\s*(?:Task|Instructions?).*?###\s*(?:Query|User|Question)\s*:?\s*\n?(.*)",
        re.DOTALL | re.IGNORECASE,
    )

    def _strip_owui_rag_context(self, text: str) -> str:
        """Strip Open WebUI's RAG context injection, returning the user's original query."""
        # Pattern 1: "### Task: ... ### Query: <user text>"
        m = self._RAG_QUERY_RE.search(text)
        if m:
            return m.group(1).strip()

        # Pattern 2: "Retrieved source N: ... \n\n<user text>"
        if "Retrieved source" in text or "retrieved source" in text.lower():
            parts = text.rsplit("\n\n", 1)
            if len(parts) == 2 and 5 < len(parts[1].strip()) < len(parts[0]):
                return parts[1].strip()

        return text

    # ========================
    # HELPERS
    # ========================

    def _extract_text(self, content) -> str:
        """Extract plain text from string or multimodal list content."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif isinstance(item, str):
                    texts.append(item)
            return " ".join(texts)
        return ""
