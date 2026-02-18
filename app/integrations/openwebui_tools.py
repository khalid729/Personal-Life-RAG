"""
Open WebUI Tools for Personal Life RAG.
Version: 2.0

Copy this file's content into Open WebUI Admin → Functions → Add Function.
Uses sync `requests` (Open WebUI runs tools synchronously).
API URL uses host.docker.internal since Open WebUI runs in Docker.

Changelog:
  v1.0 — Initial: chat, search, financial, reminders, projects, tasks, inventory, productivity, backup, graph
  v1.1 — Added: delete_reminder, update_reminder, delete_all_reminders, merge_duplicate_reminders (20 tools)
  v1.2-1.5 — store_document tool (removed in v2.0 — filter now handles files directly)
  v2.0 — Removed store_document (filter v2.0 processes files via API directly). 20 tools.
  v2.1 — Added ingest_url tool for GitHub/web URL ingestion. 21 tools.
"""

import json
import requests
from datetime import datetime
from pydantic import BaseModel, Field


class Tools:
    """Personal Life RAG Tools v2.1 — 21 tools for finances, reminders, projects, tasks, knowledge, inventory, productivity, backup, graph, and URL ingestion."""

    VERSION = "2.1"

    API_BASE = "http://host.docker.internal:8500"
    TIMEOUT = 60

    class Valves(BaseModel):
        api_base_url: str = Field(
            default="http://host.docker.internal:8500",
            description="Base URL for the Personal Life RAG API",
        )
        default_session_id: str = Field(
            default="openwebui",
            description="Default session ID for chat",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(
            f"{self.valves.api_base_url}{path}",
            params=params,
            timeout=self.TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_data: dict | None = None, timeout: int | None = None) -> dict:
        resp = requests.post(
            f"{self.valves.api_base_url}{path}",
            json=json_data,
            timeout=timeout or self.TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def chat(self, message: str, session_id: str = "") -> str:
        """
        Send a message to the Personal Life RAG system. Supports Arabic and English.
        Use this for general conversation, recording expenses, debts, reminders, or any query.

        NOTE: File uploads are handled automatically by the filter — no need to process files here.
        If the user adds a comment about an uploaded file, just send the comment via this tool.

        CRITICAL RULES for interpreting the response:
        - ONLY say an action was completed if the response contains 'STATUS: ACTION_EXECUTED'
        - If response contains 'STATUS: CONVERSATION' → this is just a conversational reply, no action was taken
        - NEVER claim an action was performed (created/deleted/merged/updated) unless STATUS: ACTION_EXECUTED is present

        :param message: The message to send (Arabic or English).
        :param session_id: Optional session ID for conversation continuity.
        :return: The assistant's reply with status prefix.
        """
        sid = session_id or self.valves.default_session_id
        result = self._post("/chat/v2", json_data={"message": message, "session_id": sid})
        reply = result.get("reply", "")

        # Check if any tool calls were executed (tool-calling mode)
        tool_calls = result.get("tool_calls", [])
        has_write = any(
            tc.get("tool") in (
                "create_reminder", "delete_reminder", "update_reminder",
                "add_expense", "record_debt", "pay_debt", "store_note",
                "manage_inventory", "manage_tasks", "manage_projects",
            ) and tc.get("success")
            for tc in tool_calls
        )
        if has_write:
            return f"STATUS: ACTION_EXECUTED — Data was stored/action was executed.\n\n{reply}"

        return f"STATUS: CONVERSATION — This is an informational/conversational reply. No data was modified.\n\n{reply}"

    def search_knowledge(self, query: str) -> str:
        """
        Search the knowledge base using vector and graph search.
        Returns relevant information from stored notes, documents, and knowledge entries.

        :param query: The search query (Arabic or English).
        :return: Search results formatted as text.
        """
        result = self._post("/search/", json_data={"query": query, "source": "auto", "limit": 5})
        results = result.get("results", [])
        if not results:
            return "لا توجد نتائج."
        lines = [f"🔍 نتائج البحث ({result.get('source_used', 'auto')}):\n"]
        for r in results:
            score = f"({r['score']:.2f})" if r.get("score") else ""
            lines.append(f"• {r['text']} {score}")
        return "\n".join(lines)

    def get_financial_report(self) -> str:
        """
        Get the current month's financial report with spending breakdown by category.

        :return: Monthly spending report in Arabic.
        """
        data = self._get("/financial/report")
        lines = [
            f"📊 التقرير المالي — {data['month']}/{data['year']}",
            f"الإجمالي: {data['total']} {data['currency']}",
            "",
        ]
        for cat in data.get("by_category", []):
            lines.append(f"• {cat['category']}: {cat['total']} ({cat['percentage']}%)")
        if not data.get("by_category"):
            lines.append("لا توجد مصاريف هذا الشهر.")
        return "\n".join(lines)

    def get_debts(self) -> str:
        """
        Get a summary of all debts — what you owe and what is owed to you.

        :return: Debt summary in Arabic.
        """
        data = self._get("/financial/debts")
        lines = [
            f"💰 ملخص الديون",
            f"عليك: {data['total_i_owe']} ريال",
            f"لك: {data['total_owed_to_me']} ريال",
            f"الصافي: {data['net_position']} ريال",
            "",
        ]
        for d in data.get("debts", []):
            direction = "عليك" if d.get("direction") == "i_owe" else "لك"
            status = d.get("status", "open")
            lines.append(f"• {d['person']}: {d['amount']} ريال ({direction}) [{status}]")
        if not data.get("debts"):
            lines.append("لا توجد ديون حالياً.")
        return "\n".join(lines)

    def get_reminders(self) -> str:
        """
        Get all active reminders including overdue ones.

        :return: Reminders list in Arabic.
        """
        data = self._get("/reminders/")
        text = data.get("reminders", "لا توجد تذكيرات.")
        return f"⏰ التذكيرات\n\n{text}"

    def delete_reminder(self, title: str) -> str:
        """
        Delete a reminder by title.

        :param title: The reminder title or keyword to match.
        :return: Deletion result.
        """
        data = self._post("/reminders/delete", json_data={"title": title})
        if data.get("error"):
            return f"خطأ: {data['error']}"
        deleted = data.get("deleted", [])
        return f"تم حذف {len(deleted)} تذكير: {', '.join(deleted)}"

    def update_reminder(self, title: str, new_title: str = "", due_date: str = "", priority: int = 0) -> str:
        """
        Update a reminder's properties.

        :param title: Current reminder title to find.
        :param new_title: New title (leave empty to keep current).
        :param due_date: New due date in ISO format (leave empty to keep current).
        :param priority: New priority 1-5 (0 to keep current).
        :return: Update result.
        """
        payload: dict = {"title": title}
        if new_title:
            payload["new_title"] = new_title
        if due_date:
            payload["due_date"] = due_date
        if priority:
            payload["priority"] = priority
        data = self._post("/reminders/update", json_data=payload)
        if data.get("error"):
            return f"خطأ: {data['error']}"
        return f"تم تحديث التذكير: {data.get('title', '?')} — الحالة: {data.get('status', '?')}"

    def delete_all_reminders(self) -> str:
        """
        Delete ALL reminders. Use with caution.

        :return: Deletion count.
        """
        data = self._post("/reminders/delete-all")
        return f"تم حذف {data.get('deleted_count', 0)} تذكير."

    def merge_duplicate_reminders(self) -> str:
        """
        Find and merge duplicate reminders. Keeps one copy per unique title.

        :return: Merge results showing what was kept and what was removed.
        """
        data = self._post("/reminders/merge-duplicates")
        groups = data.get("merged_groups", [])
        total = data.get("total_removed", 0)
        if not groups:
            return "لا توجد تكرارات للدمج."
        lines = [f"تم دمج التكرارات — حُذف {total} تذكير مكرر:\n"]
        for g in groups:
            lines.append(f"• {g['kept']} (أُبقي) — حُذف {g['removed_count']} نسخة مكررة")
        return "\n".join(lines)

    def get_projects(self, status: str = "") -> str:
        """
        Get an overview of all projects with task progress.

        :param status: Optional filter by status (active, paused, idea, done).
        :return: Projects overview in Arabic.
        """
        params = {"status": status} if status else None
        data = self._get("/projects/", params=params)
        text = data.get("projects", "لا توجد مشاريع.")
        return f"📋 المشاريع\n\n{text}"

    def get_tasks(self, status: str = "") -> str:
        """
        Get all tasks with their project links and status.

        :param status: Optional filter by status (todo, in_progress, done).
        :return: Tasks list in Arabic.
        """
        params = {"status": status} if status else None
        data = self._get("/tasks/", params=params)
        text = data.get("tasks", "لا توجد مهام.")
        return f"✅ المهام\n\n{text}"

    def daily_plan(self) -> str:
        """
        Get today's daily plan — aggregates reminders, tasks, debts, and priorities.

        :return: Today's plan in Arabic.
        """
        result = self._post("/chat/v2", json_data={
            "message": "رتب لي يومي",
            "session_id": self.valves.default_session_id,
        })
        return result.get("reply", "لا توجد خطة.")

    # --- Inventory (Phase 7-9) ---

    def get_inventory(self, search: str = "", category: str = "") -> str:
        """
        Get inventory items list, with optional search and category filter.

        :param search: Optional search keyword.
        :param category: Optional category filter.
        :return: Inventory items in Arabic.
        """
        params = {}
        if search:
            params["search"] = search
        if category:
            params["category"] = category
        data = self._get("/inventory/", params=params or None)
        text = data.get("items", "لا توجد أغراض.")
        return f"📦 المخزون\n\n{text}"

    def get_inventory_report(self) -> str:
        """
        Get comprehensive inventory report with statistics by category, location, and condition.

        :return: Inventory report in Arabic.
        """
        data = self._get("/inventory/report")
        lines = [
            f"📦 تقرير المخزون",
            f"إجمالي الأغراض: {data.get('total_items', 0)}",
            f"إجمالي الكميات: {data.get('total_quantity', 0)}",
            "",
        ]
        for cat in data.get("by_category", []):
            lines.append(f"• {cat.get('category', '?')}: {cat.get('items', 0)} غرض ({cat.get('quantity', 0)} حبة)")
        return "\n".join(lines)

    # --- Productivity (Phase 10) ---

    def get_sprints(self, status: str = "") -> str:
        """
        Get sprints list with progress information.

        :param status: Optional filter by status (active, completed).
        :return: Sprints overview.
        """
        params = {"status": status} if status else None
        data = self._get("/productivity/sprints/", params=params)
        sprints = data.get("sprints", [])
        if not sprints:
            return "لا توجد سبرنتات."
        lines = ["🏃 السبرنتات\n"]
        for s in sprints:
            name = s.get("name", "?")
            status_val = s.get("status", "?")
            lines.append(f"• {name} [{status_val}]")
        return "\n".join(lines)

    def get_focus_stats(self) -> str:
        """
        Get focus session (pomodoro) statistics — total sessions, minutes, and completion rate.

        :return: Focus stats in Arabic.
        """
        data = self._get("/productivity/focus/stats")
        return (
            f"🎯 إحصائيات التركيز\n\n"
            f"الجلسات: {data.get('total_sessions', 0)}\n"
            f"الدقائق: {data.get('total_minutes', 0)}\n"
            f"المتوسط: {data.get('avg_duration', 0)} دقيقة\n"
            f"نسبة الإكمال: {data.get('completion_rate', 0)}%"
        )

    # --- Backup (Phase 11) ---

    def create_backup(self) -> str:
        """
        Create a full system backup of graph database, vector store, and Redis memory.

        :return: Backup result with sizes.
        """
        data = self._post("/backup/create", timeout=120)
        sizes = data.get("sizes", {})
        return (
            f"💾 تم إنشاء النسخة الاحتياطية\n\n"
            f"الوقت: {data.get('timestamp', '?')}\n"
            f"Graph: {sizes.get('graph', 0):,} bytes\n"
            f"Vector: {sizes.get('vector', 0):,} bytes\n"
            f"Redis: {sizes.get('redis', 0):,} bytes"
        )

    def list_backups(self) -> str:
        """
        List all available system backups.

        :return: List of backups with timestamps and sizes.
        """
        data = self._get("/backup/list")
        backups = data.get("backups", [])
        if not backups:
            return "لا توجد نسخ احتياطية."
        lines = ["💾 النسخ الاحتياطية\n"]
        for b in backups:
            lines.append(f"• {b.get('timestamp', '?')}")
        return "\n".join(lines)

    # --- Graph Visualization (Phase 11) ---

    def get_graph_schema(self) -> str:
        """
        Get knowledge graph schema — node labels, relationship types, and counts.

        :return: Graph schema overview.
        """
        data = self._get("/graph/schema")
        lines = [
            f"🕸️ مخطط الغراف",
            f"العقد: {data.get('total_nodes', 0)}",
            f"العلاقات: {data.get('total_edges', 0)}",
            "",
            "الأنواع:",
        ]
        for label, count in data.get("node_labels", {}).items():
            lines.append(f"• {label}: {count}")
        return "\n".join(lines)

    def ingest_url(self, url: str, topic: str = "") -> str:
        """
        Fetch and ingest content from a URL (GitHub repos, web pages, docs).
        Use this when the user shares a link and wants to store/analyze its content.

        :param url: The URL to fetch and ingest.
        :param topic: Optional topic to categorize the content.
        :return: Ingestion result summary.
        """
        data = self._post("/ingest/url", json_data={"url": url, "topic": topic}, timeout=120)
        if data.get("status") == "error":
            return f"خطأ: {data.get('error', 'فشل سحب المحتوى')}"
        lines = [
            f"STATUS: ACTION_EXECUTED — تم سحب وتخزين محتوى الرابط بنجاح.",
            f"الرابط: {url}",
            f"الأجزاء المخزنة: {data.get('chunks_stored', 0)}",
            f"الحقائق المستخرجة: {data.get('facts_extracted', 0)}",
        ]
        entities = data.get("entities", [])
        if entities:
            lines.append("المعلومات المستخرجة:")
            for ent in entities:
                ent_type = ent.get("entity_type", "")
                ent_name = ent.get("entity_name", "")
                props = ent.get("properties", {})
                desc = props.get("description", "")
                line = f"  - [{ent_type}] {ent_name}"
                if desc:
                    line += f": {desc[:100]}"
                lines.append(line)
        return "\n".join(lines)

    def get_graph_stats(self) -> str:
        """
        Get knowledge graph statistics — total nodes, edges, and counts by type.

        :return: Graph statistics.
        """
        data = self._get("/graph/stats")
        lines = [
            f"📊 إحصائيات الغراف",
            f"العقد: {data.get('total_nodes', 0)}",
            f"العلاقات: {data.get('total_edges', 0)}",
            "",
        ]
        for node_type, count in data.get("by_type", {}).items():
            lines.append(f"• {node_type}: {count}")
        return "\n".join(lines)
