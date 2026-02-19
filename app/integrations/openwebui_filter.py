"""
Open WebUI Filter for Personal Life RAG.
Version: 2.1

File-processing-only filter — designed to work alongside the Pipe (openwebui_pipe.py).

The Pipe handles chat routing (sends to /chat/v2), while this Filter handles file
ingestion only: detects uploaded files in inlet(), reads raw bytes from Docker path,
sends to /ingest/file, and injects results into the user message.

Copy this file's content into Open WebUI Admin → Functions → Add Function (type: Filter).
Attach both this Filter AND the Pipe to the same model. Set Pipe's auto_process_files = False.

Changelog:
  v1.0 — Initial: date/time injection + anti-lying STATUS rules
  v1.1-1.3 — store_document LLM tool-calling approach (replaced in v2.0)
  v2.0 — Direct API file processing: filter calls /ingest/file directly, no LLM tool-calling needed
  v2.1 — File-only filter for Pipe pairing: removed system prompt injection, Strategy 2, text fallback.
         Added text MIME types (.md, .txt, .csv, .log, .json, .xml, .yaml, .yml, .py, .js, .ts).
"""

import base64
import re
import requests
from typing import Optional, List
from pydantic import BaseModel, Field


class Filter:
    """Personal Life RAG Filter v2.1 — File processing only (pairs with Pipe for chat)."""

    VERSION = "2.1"

    class Valves(BaseModel):
        api_url: str = Field(
            default="http://host.docker.internal:8500",
            description="Personal Life RAG API URL",
        )
        auto_process: bool = Field(
            default=True,
            description="Automatically process uploaded files via API",
        )
        debug_mode: bool = Field(
            default=False,
            description="Send full inlet body to API debug endpoint for inspection",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ========================
    # FILE EXTRACTION
    # ========================

    def _extract_files(self, message: dict) -> List[dict]:
        """Extract files from message — handles base64, paths, multimodal content, files/images arrays."""
        files = []
        content = message.get("content", "")

        # Check multimodal content (list format)
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "image_url":
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "")
                        if url.startswith("data:"):
                            files.append({
                                "type": "image",
                                "data": url,
                                "filename": "uploaded_image",
                            })
                    elif item.get("type") == "file":
                        files.append({
                            "type": item.get("file_type", "unknown"),
                            "data": item.get("data", ""),
                            "path": item.get("path", ""),
                            "filename": item.get("name", "unknown"),
                        })

        # Check files array in message metadata
        if "files" in message:
            for f in message["files"]:
                file_data = {
                    "type": f.get("type", "unknown"),
                    "filename": f.get("name", f.get("filename", "unknown")),
                }
                if f.get("data"):
                    file_data["data"] = f["data"]
                if f.get("path"):
                    file_data["path"] = f["path"]
                if f.get("url"):
                    file_data["url"] = f["url"]
                files.append(file_data)

        # Check images array
        if "images" in message:
            for img in message["images"]:
                if isinstance(img, str):
                    if img.startswith("data:") or img.startswith("http"):
                        files.append({
                            "type": "image",
                            "data": img,
                            "filename": "image",
                        })

        return files

    def _extract_text_from_content(self, content) -> str:
        """Get plain text from string or list content."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif isinstance(item, str):
                    texts.append(item)
            return " ".join(texts)
        return ""

    # ========================
    # API CALLS
    # ========================

    def _process_file_via_api(self, file_info: dict, user_text: str = "") -> Optional[dict]:
        """Send file to /ingest/file and return API response dict."""
        try:
            file_data = file_info.get("data", "")
            file_path = file_info.get("path", "")
            filename = file_info.get("filename", "unknown")

            if file_data and isinstance(file_data, str) and file_data.startswith("data:"):
                # Base64 data URL → decode and send
                try:
                    header, encoded = file_data.split(",", 1)
                    file_bytes = base64.b64decode(encoded)

                    mime_match = re.match(r"data:([^;]+)", header)
                    mime_type = mime_match.group(1) if mime_match else "application/octet-stream"

                    ext_map = {
                        "image/jpeg": ".jpg",
                        "image/png": ".png",
                        "image/gif": ".gif",
                        "image/webp": ".webp",
                        "application/pdf": ".pdf",
                        "audio/mpeg": ".mp3",
                        "audio/wav": ".wav",
                        "audio/mp4": ".m4a",
                    }
                    ext = ext_map.get(mime_type, ".bin")
                    upload_filename = filename if filename != "uploaded_image" else f"upload{ext}"

                    response = requests.post(
                        f"{self.valves.api_url}/ingest/file",
                        files={"file": (upload_filename, file_bytes, mime_type)},
                        data={"context": user_text},
                        timeout=180,
                    )

                    if response.status_code == 200:
                        return response.json()
                    else:
                        return {"status": "error", "error": f"HTTP {response.status_code}"}

                except Exception as e:
                    return {"status": "error", "error": f"Base64 decode error: {str(e)}"}

            elif file_path:
                # File path → read and send
                import os
                if os.path.exists(file_path):
                    # Use provided filename, fallback to basename
                    upload_name = filename if filename != "unknown" else os.path.basename(file_path)
                    # Detect content type from extension
                    ext = os.path.splitext(file_path)[1].lower()
                    ct_map = {
                        ".pdf": "application/pdf",
                        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".gif": "image/gif",
                        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
                        ".md": "text/markdown", ".markdown": "text/markdown",
                        ".txt": "text/plain", ".text": "text/plain",
                        ".csv": "text/plain", ".log": "text/plain",
                        ".json": "application/json",
                        ".xml": "application/xml",
                        ".yaml": "text/plain", ".yml": "text/plain",
                        ".py": "text/plain", ".js": "text/plain", ".ts": "text/plain",
                    }
                    content_type = ct_map.get(ext, "application/octet-stream")

                    with open(file_path, "rb") as f:
                        response = requests.post(
                            f"{self.valves.api_url}/ingest/file",
                            files={"file": (upload_name, f, content_type)},
                            data={"context": user_text},
                            timeout=180,
                        )

                    if response.status_code == 200:
                        return response.json()
                    else:
                        return {"status": "error", "error": f"HTTP {response.status_code}: {response.text[:200]}"}
                else:
                    return {"status": "error", "error": f"File not found: {file_path}"}

            else:
                return None

        except requests.exceptions.Timeout:
            return {"status": "error", "error": "Request timeout — file may be too large"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ========================
    # RESULT FORMATTING
    # ========================

    def _format_result(self, result: dict) -> str:
        """Format API response for display in the message."""
        status = result.get("status", "unknown")

        if status == "error":
            error = result.get("error", result.get("analysis", {}).get("error", "Unknown"))
            return f"خطأ في المعالجة: {error}"

        if status == "duplicate":
            filename = result.get("filename", "")
            return f"الملف موجود مسبقاً: {filename}"

        parts = []

        # File type
        file_type = result.get("file_type", "")
        if file_type:
            type_labels = {
                "pdf_document": "مستند PDF",
                "invoice": "فاتورة",
                "official_document": "مستند رسمي",
                "personal_photo": "صورة شخصية",
                "info_image": "صورة معلومات",
                "business_card": "بطاقة عمل",
                "inventory_item": "غرض/منتج",
                "audio_recording": "تسجيل صوتي",
                "note": "ملاحظة",
            }
            parts.append(f"النوع: {type_labels.get(file_type, file_type)}")

        # Chunks and facts
        chunks = result.get("chunks_stored", 0)
        facts = result.get("facts_extracted", 0)
        if chunks > 0 or facts > 0:
            parts.append(f"تم تخزين {chunks} جزء واستخراج {facts} حقيقة")

        # Entities
        entities = result.get("entities", [])
        if entities:
            parts.append("المعلومات المستخرجة:")
            for ent in entities:
                ent_type = ent.get("entity_type", "")
                ent_name = ent.get("entity_name", "")
                props = ent.get("properties", {})

                # Format entity with key properties
                prop_parts = []
                for k, v in props.items():
                    if v and k not in ("name", "title", "entity_type"):
                        prop_parts.append(f"{k}: {v}")

                entity_line = f"  - [{ent_type}] {ent_name}"
                if prop_parts:
                    entity_line += f" ({', '.join(prop_parts[:5])})"
                parts.append(entity_line)

        # Analysis preview (for PDFs or images without entities)
        if not entities:
            analysis = result.get("analysis", {})
            preview = analysis.get("preview", "")
            if preview:
                # Truncate for display
                if len(preview) > 300:
                    preview = preview[:300] + "..."
                parts.append(f"معاينة: {preview}")

            # Auto expense
            auto_expense = result.get("auto_expense")
            if auto_expense:
                amount = auto_expense.get("amount", 0)
                vendor = auto_expense.get("vendor", "")
                parts.append(f"مصروف تلقائي: {amount} ر.س" + (f" ({vendor})" if vendor else ""))

            # Auto item
            auto_item = result.get("auto_item")
            if auto_item:
                item_name = auto_item.get("name", "")
                parts.append(f"غرض مضاف: {item_name}")

        return "\n".join(parts) if parts else f"تمت المعالجة (الحالة: {status})"

    # ========================
    # INLET / OUTLET
    # ========================

    def inlet(self, body: dict, __user__: dict = {}) -> dict:
        """Process uploaded files before the message goes to the Pipe/LLM."""
        # Debug: send full body to API for inspection
        if self.valves.debug_mode:
            try:
                requests.post(
                    f"{self.valves.api_url}/debug/filter-inlet",
                    json=body,
                    timeout=5,
                )
            except Exception:
                pass

        if not self.valves.auto_process:
            return body

        messages = body.get("messages", [])
        if not messages:
            return body

        last_message = messages[-1] if messages[-1].get("role") == "user" else None

        if not last_message:
            return body

        user_text = self._extract_text_from_content(last_message.get("content", ""))
        file_results = []

        # Direct file attachments (base64, path, multimodal)
        files = self._extract_files(last_message)

        # Also check body-level files (Open WebUI structure)
        # Open WebUI sends: body["files"] = [{"type":"file", "file":{"path":"/app/backend/data/uploads/..."}, "name":"...", "content_type":"..."}]
        if not files and body.get("files"):
            for f in body["files"]:
                file_obj = f.get("file", {})
                file_data = {
                    "type": f.get("content_type", f.get("type", "unknown")),
                    "filename": f.get("name", file_obj.get("filename", "unknown")),
                }
                # Open WebUI stores file at file.path (Docker path)
                file_path = file_obj.get("path", "") or f.get("path", "")
                if file_path:
                    file_data["path"] = file_path
                if f.get("data") and isinstance(f["data"], str):
                    file_data["data"] = f["data"]
                files.append(file_data)

        if files:
            for file_info in files:
                result = self._process_file_via_api(file_info, user_text)
                if result:
                    file_results.append(self._format_result(result))

        # Inject results into user message
        if file_results:
            result_text = "\n\n".join(file_results)
            injection = f"\n\n---\nنتيجة معالجة الملف:\n{result_text}\n---"

            content = last_message.get("content", "")
            if isinstance(content, list):
                text_updated = False
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text" and not text_updated:
                        item["text"] = item.get("text", "") + injection
                        text_updated = True
                if not text_updated:
                    content.append({"type": "text", "text": injection})
                last_message["content"] = content
            else:
                last_message["content"] = str(content) + injection

        body["messages"] = messages
        return body

    def outlet(self, body: dict, __user__: dict = {}) -> dict:
        """Modify response after LLM generates it (no-op)."""
        return body
