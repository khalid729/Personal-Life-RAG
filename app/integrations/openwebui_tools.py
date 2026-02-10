"""
Open WebUI Tools for Personal Life RAG.

Copy this file's content into Open WebUI Admin → Functions → Add Function.
Uses sync `requests` (Open WebUI runs tools synchronously).
API URL uses host.docker.internal since Open WebUI runs in Docker.
"""

import json
import requests
from datetime import datetime
from pydantic import BaseModel, Field


class Tools:
    """Personal Life RAG — tools for managing finances, reminders, projects, tasks, and knowledge."""

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

        :param message: The message to send (Arabic or English).
        :param session_id: Optional session ID for conversation continuity.
        :return: The assistant's reply.
        """
        sid = session_id or self.valves.default_session_id
        result = self._post("/chat/", json_data={"message": message, "session_id": sid})
        reply = result.get("reply", "")
        if result.get("pending_confirmation"):
            reply += "\n\n⚠️ يحتاج تأكيد — أرسل 'نعم' أو 'لا' عبر chat tool."
        return reply

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
        result = self._post("/chat/", json_data={
            "message": "رتب لي يومي",
            "session_id": self.valves.default_session_id,
        })
        return result.get("reply", "لا توجد خطة.")
