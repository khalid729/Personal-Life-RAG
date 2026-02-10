import calendar
import logging
import re
from datetime import datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from falkordb.asyncio import FalkorDB
from redis.asyncio import BlockingConnectionPool

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class GraphService:
    def __init__(self):
        self._db: FalkorDB | None = None
        self._pool: BlockingConnectionPool | None = None
        self._graph = None
        self._vector_service = None

    def set_vector_service(self, vector_service) -> None:
        """Allow graph service to use vector for idea similarity detection."""
        self._vector_service = vector_service

    async def start(self):
        self._pool = BlockingConnectionPool(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            max_connections=16,
            timeout=None,
            decode_responses=True,
        )
        self._db = FalkorDB(connection_pool=self._pool)
        self._graph = self._db.select_graph(settings.falkordb_graph_name)
        logger.info("FalkorDB connected: %s", settings.falkordb_graph_name)

    async def stop(self):
        if self._pool:
            await self._pool.aclose()

    async def query(self, cypher: str, params: dict | None = None) -> list[list]:
        result = await self._graph.query(cypher, params=params)
        return result.result_set

    # --- Person ---
    async def upsert_person(self, name: str, **props) -> None:
        props_str = self._build_set_clause(props)
        q = f"""
        MERGE (p:Person {{name: $name}})
        ON CREATE SET p.created_at = $now {props_str}
        ON MATCH SET p.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Project ---
    async def upsert_project(self, name: str, **props) -> None:
        props_str = self._build_set_clause(props)
        q = f"""
        MERGE (p:Project {{name: $name}})
        ON CREATE SET p.created_at = $now {props_str}
        ON MATCH SET p.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Expense ---
    async def create_expense(self, description: str, amount: float, **props) -> None:
        q = """
        CREATE (e:Expense {description: $description, amount: $amount, created_at: $now})
        """
        extra = {k: v for k, v in props.items() if v is not None}
        if extra:
            sets = ", ".join(f"e.{k} = ${k}" for k in extra)
            q = f"""
            CREATE (e:Expense {{description: $description, amount: $amount, created_at: $now}})
            SET {sets}
            """
        await self._graph.query(
            q, params={"description": description, "amount": amount, "now": _now(), **extra}
        )

    # --- Debt ---
    @staticmethod
    def _normalize_direction(direction: str) -> str:
        """Normalize debt direction to canonical values: 'i_owe' or 'owed_to_me'."""
        d = direction.lower().strip()
        if d in ("owed_by_me", "i_owe", "i owe", "i_owe_them", "owed_to_other"):
            return "i_owe"
        if d in ("owed_to_me", "they_owe", "they owe me", "they_owe_me"):
            return "owed_to_me"
        return d

    # --- Location normalization ---
    _LOCATION_ALIASES: dict[str, str | None] = {
        "bedroom": "غرفة النوم",
        "kitchen": "المطبخ",
        "bathroom": "الحمام",
        "living room": "الصالة",
        "garage": "الكراج",
        "roof": "السطح",
        "storage": "المخزن",
        "office": "المكتب",
    }

    @staticmethod
    def _normalize_location(path: str) -> str | None:
        """Normalize location path to consistent form."""
        if not path:
            return None
        path = path.strip()
        if not path:
            return None
        # Check alias map (English → Arabic normalization)
        lower = path.lower()
        if lower in GraphService._LOCATION_ALIASES:
            return GraphService._LOCATION_ALIASES[lower]
        # Normalize separator spacing: "السطح  >الرف" → "السطح > الرف"
        path = re.sub(r'\s*>\s*', ' > ', path)
        # Collapse multiple spaces
        path = re.sub(r'\s+', ' ', path)
        return path.strip() or None

    async def upsert_debt(self, person_name: str, amount: float, direction: str, **props) -> None:
        direction = self._normalize_direction(direction)
        q = """
        MERGE (p:Person {name: $person_name})
        ON CREATE SET p.created_at = $now
        CREATE (d:Debt {amount: $amount, direction: $direction, status: 'open', created_at: $now})
        MERGE (d)-[:INVOLVES]->(p)
        """
        await self._graph.query(
            q,
            params={
                "person_name": person_name,
                "amount": amount,
                "direction": direction,
                "now": _now(),
                **{k: v for k, v in props.items() if v is not None},
            },
        )

    # --- Reminder ---
    async def create_reminder(self, title: str, **props) -> None:
        extra = {k: v for k, v in props.items() if v is not None}
        # Ensure snooze_count defaults to 0
        if "snooze_count" not in extra:
            extra["snooze_count"] = 0
        sets = ""
        if extra:
            sets = "SET " + ", ".join(f"r.{k} = ${k}" for k in extra)
        q = f"""
        CREATE (r:Reminder {{title: $title, status: 'pending', created_at: $now}})
        {sets}
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **extra})

    async def update_reminder_status(
        self, title: str, action: str, snooze_until: str | None = None
    ) -> dict:
        """Mark reminder done/snoozed/cancelled. Returns updated info."""
        if action == "done":
            q = """
            MATCH (r:Reminder) WHERE toLower(r.title) CONTAINS toLower($title)
            SET r.status = 'done', r.completed_at = $now
            RETURN r.title, r.status
            """
            rows = await self.query(q, {"title": title, "now": _now()})
        elif action == "snooze":
            q = """
            MATCH (r:Reminder) WHERE toLower(r.title) CONTAINS toLower($title)
            SET r.status = 'snoozed',
                r.snooze_count = coalesce(r.snooze_count, 0) + 1,
                r.snoozed_until = $snooze_until
            RETURN r.title, r.status, r.snooze_count
            """
            rows = await self.query(q, {"title": title, "snooze_until": snooze_until or ""})
        elif action == "cancel":
            q = """
            MATCH (r:Reminder) WHERE toLower(r.title) CONTAINS toLower($title)
            SET r.status = 'cancelled', r.cancelled_at = $now
            RETURN r.title, r.status
            """
            rows = await self.query(q, {"title": title, "now": _now()})
        else:
            return {"error": f"Unknown action: {action}"}

        if not rows:
            return {"error": f"No reminder found matching '{title}'"}
        return {"title": rows[0][0], "status": rows[0][1]}

    async def advance_recurring_reminder(self, title: str, recurrence: str) -> dict:
        """Advance a recurring reminder to its next due date."""
        q_find = """
        MATCH (r:Reminder)
        WHERE toLower(r.title) CONTAINS toLower($title)
          AND r.status = 'pending'
        RETURN r.title, r.due_date
        LIMIT 1
        """
        rows = await self.query(q_find, {"title": title})
        if not rows:
            return {"error": f"No pending reminder found matching '{title}'"}

        r_title, due_date_str = rows[0][0], rows[0][1]
        if not due_date_str:
            return {"error": f"Reminder '{r_title}' has no due_date to advance"}

        # Parse current due date
        try:
            current_due = datetime.fromisoformat(due_date_str)
        except (ValueError, TypeError):
            current_due = datetime.fromisoformat(due_date_str[:19])

        # Calculate next due date based on recurrence
        rec = recurrence.lower().strip()
        if rec == "daily":
            next_due = current_due + timedelta(days=1)
        elif rec == "weekly":
            next_due = current_due + timedelta(weeks=1)
        elif rec == "monthly":
            next_due = current_due + relativedelta(months=1)
        elif rec == "yearly":
            next_due = current_due + relativedelta(years=1)
        else:
            return {"error": f"Unknown recurrence: {recurrence}"}

        next_due_str = next_due.isoformat()
        q_update = """
        MATCH (r:Reminder)
        WHERE toLower(r.title) CONTAINS toLower($title)
          AND r.status = 'pending'
        SET r.due_date = $next_due, r.updated_at = $now
        """
        await self.query(q_update, {"title": title, "next_due": next_due_str, "now": _now()})

        return {"title": r_title, "next_due": next_due_str, "recurrence": recurrence}

    # --- Task ---
    async def upsert_task(self, title: str, **props) -> None:
        props_str = self._build_set_clause(props, var="t")
        q = f"""
        MERGE (t:Task {{title: $title}})
        ON CREATE SET t.status = 'todo', t.created_at = $now {props_str}
        ON MATCH SET t.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **props})

    # --- Idea ---
    async def create_idea(self, title: str, **props) -> None:
        extra = {k: v for k, v in props.items() if v is not None}
        inline = ""
        if extra:
            inline = ", " + ", ".join(f"{k}: ${k}" for k in extra)
        q = f"""
        CREATE (i:Idea {{title: $title, created_at: $now{inline}}})
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **extra})

    # --- Company ---
    async def upsert_company(self, name: str, **props) -> None:
        props_str = self._build_set_clause(props, var="c")
        q = f"""
        MERGE (c:Company {{name: $name}})
        ON CREATE SET c.created_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Topic ---
    async def upsert_topic(self, name: str, **props) -> None:
        props_str = self._build_set_clause(props, var="t")
        q = f"""
        MERGE (t:Topic {{name: $name}})
        ON CREATE SET t.created_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Tag ---
    async def upsert_tag(self, name: str) -> None:
        q = "MERGE (t:Tag {name: $name}) ON CREATE SET t.created_at = $now"
        await self._graph.query(q, params={"name": name, "now": _now()})

    # --- File ---
    async def upsert_file_node(
        self, file_hash: str, filename: str, file_type: str, analysis: dict
    ) -> None:
        description = analysis.get("brief_description") or analysis.get("description") or ""
        q = """
        MERGE (f:File {file_hash: $file_hash})
        ON CREATE SET f.filename = $filename, f.file_type = $file_type,
                      f.description = $description, f.created_at = $now
        ON MATCH SET f.filename = $filename, f.file_type = $file_type,
                     f.description = $description, f.updated_at = $now
        """
        await self._graph.query(
            q,
            params={
                "file_hash": file_hash,
                "filename": filename,
                "file_type": file_type,
                "description": description[:500],
                "now": _now(),
            },
        )

    async def find_file_by_hash(self, file_hash: str) -> dict | None:
        """Check if a file with this hash already exists in the graph."""
        q = "MATCH (f:File {file_hash: $hash}) RETURN f"
        rows = await self.query(q, {"hash": file_hash})
        if rows and rows[0]:
            node = rows[0][0]
            props = node.properties if hasattr(node, "properties") else {}
            return {"file_type": props.get("file_type"), "properties": props}
        return None

    # --- Relationships ---
    async def create_relationship(
        self,
        from_label: str,
        from_key: str,
        from_value: str,
        rel_type: str,
        to_label: str,
        to_key: str,
        to_value: str,
    ) -> None:
        q = f"""
        MATCH (a:{from_label} {{{from_key}: $from_val}})
        MATCH (b:{to_label} {{{to_key}: $to_val}})
        MERGE (a)-[:{rel_type}]->(b)
        """
        await self._graph.query(q, params={"from_val": from_value, "to_val": to_value})

    # --- Upsert from LLM-extracted facts ---
    async def upsert_from_facts(self, facts: dict) -> int:
        count = 0
        for entity in facts.get("entities", []):
            etype = entity.get("entity_type", "")
            ename = entity.get("entity_name", "")
            props = entity.get("properties", {})
            rels = entity.get("relationships", [])

            if not etype or not ename:
                continue

            try:
                handler = {
                    "Person": lambda n, **p: self.upsert_person(n, **p),
                    "Company": lambda n, **p: self.upsert_company(n, **p),
                    "Project": lambda n, **p: self.upsert_project(n, **p),
                    "Task": lambda n, **p: self.upsert_task(n, **p),
                    "Idea": lambda n, **p: self.create_idea(n, **p),
                    "Topic": lambda n, **p: self.upsert_topic(n, **p),
                    "Tag": lambda n, **p: self.upsert_tag(n),
                    "Reminder": lambda n, **p: self.create_reminder(n, **p),
                    "Knowledge": lambda n, **p: self._create_generic("Knowledge", "title", n, **p),
                    "Item": lambda n, **p: self.upsert_item(n, **p),
                }.get(etype)

                if etype == "DebtPayment":
                    person = ""
                    for r in rels:
                        if r.get("target_type") == "Person":
                            person = r.get("target_name", "")
                            break
                    amount = props.pop("amount", 0)
                    direction = props.pop("direction", None)
                    if person and amount > 0:
                        result = await self.record_debt_payment(person, amount, direction)
                        if "error" not in result:
                            count += 1
                        else:
                            logger.warning("DebtPayment failed: %s", result["error"])
                    continue  # Skip relationship creation for pseudo-entity

                if etype == "ItemUsage":
                    qty_used = props.get("quantity_used", 1)
                    result = await self.adjust_item_quantity(ename, -abs(int(qty_used)))
                    if "error" not in result:
                        count += 1
                    else:
                        logger.warning("ItemUsage failed: %s", result["error"])
                    continue  # Skip relationship creation for pseudo-entity

                if etype == "Expense":
                    amount = props.pop("amount", 0)
                    await self.create_expense(ename, amount, **props)
                    count += 1
                elif etype == "Idea" and handler:
                    await handler(ename, **props)
                    count += 1
                    # Idea similarity: embed + find similar ideas
                    await self._detect_similar_ideas(ename, props.get("description", ""))
                elif etype == "Debt":
                    person = ""
                    for r in rels:
                        if r.get("target_type") == "Person":
                            person = r.get("target_name", "")
                            break
                    amount = props.pop("amount", 0)
                    direction = props.pop("direction", "i_owe")
                    await self.upsert_debt(person or ename, amount, direction, **props)
                    count += 1
                elif handler:
                    await handler(ename, **props)
                    count += 1

                # Create relationships
                for rel in rels:
                    target_type = rel.get("target_type", "")
                    target_name = rel.get("target_name", "")
                    rel_type = rel.get("type", "RELATED_TO")
                    if target_type and target_name and etype not in ("Debt",):
                        key_field = "name" if etype not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
                        target_key = "name" if target_type not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
                        try:
                            await self.create_relationship(
                                etype, key_field, ename, rel_type, target_type, target_key, target_name
                            )
                        except Exception as e:
                            logger.debug("Relationship creation skipped: %s", e)
            except Exception as e:
                logger.warning("Failed to upsert entity %s/%s: %s", etype, ename, e)
        return count

    # --- GraphRAG queries ---
    async def query_person_context(self, name: str) -> str:
        q = """
        MATCH (p:Person {name: $name})
        OPTIONAL MATCH (p)-[r1]-(n1)
        OPTIONAL MATCH (n1)-[r2]-(n2)
        RETURN p, type(r1) as rel1, labels(n1)[0] as label1, n1,
               type(r2) as rel2, labels(n2)[0] as label2, n2
        LIMIT 50
        """
        rows = await self.query(q, {"name": name})
        return self._format_graph_context(rows)

    async def query_project_context(self, name: str) -> str:
        q = """
        MATCH (p:Project {name: $name})
        OPTIONAL MATCH (p)-[r1]-(n1)
        OPTIONAL MATCH (n1)-[r2]-(n2)
        RETURN p, type(r1) as rel1, labels(n1)[0] as label1, n1,
               type(r2) as rel2, labels(n2)[0] as label2, n2
        LIMIT 50
        """
        rows = await self.query(q, {"name": name})
        return self._format_graph_context(rows)

    async def query_financial_summary(self, detailed: bool = False) -> str:
        parts = []
        now = datetime.utcnow()
        month_start = f"{now.year}-{now.month:02d}-01"
        _, last_day = calendar.monthrange(now.year, now.month)
        month_end = f"{now.year}-{now.month:02d}-{last_day:02d}"

        # Monthly total + category breakdown
        q_monthly = """
        MATCH (e:Expense)
        WHERE e.date >= $start AND e.date <= $end
        RETURN e.category, sum(e.amount) as total, count(e) as cnt
        ORDER BY total DESC
        """
        rows = await self.query(q_monthly, {"start": month_start, "end": month_end})
        grand_total = sum(r[1] for r in rows) if rows else 0
        if rows:
            parts.append(f"This month ({now.strftime('%B %Y')}): {grand_total:.0f} SAR total")
            for r in rows:
                cat = r[0] or "uncategorized"
                pct = (r[1] / grand_total * 100) if grand_total else 0
                parts.append(f"  - {cat}: {r[1]:.0f} SAR ({r[2]} items, {pct:.0f}%)")
        else:
            parts.append(f"No expenses recorded for {now.strftime('%B %Y')}.")

        # Recent expenses
        q1 = "MATCH (e:Expense) RETURN e.description, e.amount, e.category, e.created_at ORDER BY e.created_at DESC LIMIT 10"
        rows = await self.query(q1)
        if rows:
            parts.append("\nRecent expenses:")
            for r in rows:
                parts.append(f"  - {r[0]}: {r[1]} SAR ({r[2] or 'uncategorized'})")

        # Open/partial debts
        q2 = """
        MATCH (d:Debt)-[:INVOLVES]->(p:Person)
        WHERE d.status IN ['open', 'partial']
        RETURN p.name, d.amount, d.direction, d.status, d.original_amount
        """
        rows = await self.query(q2)
        if rows:
            parts.append("\nOpen debts:")
            for r in rows:
                direction = "they owe me" if r[2] == "owed_to_me" else "I owe them"
                status_tag = f" [partial, originally {r[4]}]" if r[3] == "partial" and r[4] else ""
                parts.append(f"  - {r[0]}: {r[1]} SAR ({direction}){status_tag}")

        # Spending alerts (if detailed)
        if detailed:
            alerts = await self.query_spending_alerts()
            if alerts:
                parts.append(f"\n{alerts}")

        return "\n".join(parts) if parts else "No financial data found."

    async def query_monthly_report(self, month: int, year: int) -> dict:
        """Get spending report for a specific month with category breakdown."""
        _, last_day = calendar.monthrange(year, month)
        start = f"{year}-{month:02d}-01"
        end = f"{year}-{month:02d}-{last_day:02d}"

        q = """
        MATCH (e:Expense)
        WHERE e.date >= $start AND e.date <= $end
        RETURN e.category, sum(e.amount) as total, count(e) as cnt
        ORDER BY total DESC
        """
        rows = await self.query(q, {"start": start, "end": end})
        grand_total = sum(r[1] for r in rows) if rows else 0

        categories = []
        for r in rows:
            pct = (r[1] / grand_total * 100) if grand_total else 0
            categories.append({
                "category": r[0] or "uncategorized",
                "total": r[1],
                "count": r[2],
                "percentage": round(pct, 1),
            })

        return {
            "month": month,
            "year": year,
            "total": grand_total,
            "currency": "SAR",
            "by_category": categories,
        }

    async def query_month_comparison(self, month: int, year: int) -> dict:
        """Compare current month spending vs previous month."""
        current = await self.query_monthly_report(month, year)

        # Previous month
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        previous = await self.query_monthly_report(prev_month, prev_year)

        diff = current["total"] - previous["total"]
        pct_change = (diff / previous["total"] * 100) if previous["total"] else 0

        current["comparison"] = {
            "previous_month": prev_month,
            "previous_year": prev_year,
            "previous_total": previous["total"],
            "difference": round(diff, 2),
            "percentage_change": round(pct_change, 1),
        }
        return current

    async def query_spending_alerts(self) -> str:
        """Flag categories where current month spending > 40% above 3-month avg."""
        now = datetime.utcnow()
        _, last_day = calendar.monthrange(now.year, now.month)
        cur_start = f"{now.year}-{now.month:02d}-01"
        cur_end = f"{now.year}-{now.month:02d}-{last_day:02d}"

        # 3-month rolling average by category
        m3, y3 = now.month - 3, now.year
        if m3 <= 0:
            m3 += 12
            y3 -= 1
        avg_start = f"{y3}-{m3:02d}-01"

        # Previous 3 months (excluding current)
        prev_end_month = now.month - 1 if now.month > 1 else 12
        prev_end_year = now.year if now.month > 1 else now.year - 1
        _, prev_last = calendar.monthrange(prev_end_year, prev_end_month)
        avg_end = f"{prev_end_year}-{prev_end_month:02d}-{prev_last:02d}"

        q_avg = """
        MATCH (e:Expense)
        WHERE e.date >= $start AND e.date <= $end
        RETURN e.category, sum(e.amount) / 3.0 as monthly_avg
        """
        avg_rows = await self.query(q_avg, {"start": avg_start, "end": avg_end})
        avg_map = {(r[0] or "uncategorized"): r[1] for r in avg_rows} if avg_rows else {}

        q_cur = """
        MATCH (e:Expense)
        WHERE e.date >= $start AND e.date <= $end
        RETURN e.category, sum(e.amount) as total
        """
        cur_rows = await self.query(q_cur, {"start": cur_start, "end": cur_end})

        alerts = []
        for r in cur_rows or []:
            cat = r[0] or "uncategorized"
            current_total = r[1]
            avg = avg_map.get(cat, 0)
            if avg > 0 and current_total > avg * 1.4:
                pct_over = ((current_total - avg) / avg * 100)
                alerts.append(f"  ⚠ {cat}: {current_total:.0f} SAR (+{pct_over:.0f}% above 3-month avg of {avg:.0f})")

        if alerts:
            return "Spending alerts:\n" + "\n".join(alerts)
        return ""

    async def query_debt_summary(self) -> dict:
        """All open/partial debts with totals and net position."""
        q = """
        MATCH (d:Debt)-[:INVOLVES]->(p:Person)
        WHERE d.status IN ['open', 'partial']
        RETURN p.name, d.amount, d.direction, d.status, d.original_amount, d.reason
        """
        rows = await self.query(q)

        total_i_owe = 0.0
        total_owed_to_me = 0.0
        debts = []

        for r in rows or []:
            person, amount, direction, status, orig_amount, reason = r[0], r[1], r[2], r[3], r[4], r[5]
            if direction == "i_owe":
                total_i_owe += amount
            else:
                total_owed_to_me += amount
            debts.append({
                "person": person,
                "amount": amount,
                "direction": direction,
                "status": status,
                "original_amount": orig_amount,
                "reason": reason or "",
            })

        return {
            "total_i_owe": total_i_owe,
            "total_owed_to_me": total_owed_to_me,
            "net_position": total_owed_to_me - total_i_owe,
            "debts": debts,
        }

    async def record_debt_payment(
        self, person: str, amount: float, direction: str | None = None
    ) -> dict:
        """Record a debt payment. Finds matching open/partial debt, updates amount/status.
        Returns disambiguation_needed if multiple debts match."""
        # Find matching debts (no LIMIT 1 — check for disambiguation)
        direction_clause = "AND d.direction = $direction" if direction else ""
        q_find = f"""
        MATCH (d:Debt)-[:INVOLVES]->(p:Person)
        WHERE toLower(p.name) CONTAINS toLower($person)
          AND d.status IN ['open', 'partial']
          {direction_clause}
        RETURN id(d) as debt_id, d.amount, d.direction, p.name, d.original_amount, d.reason
        ORDER BY d.amount DESC
        """
        params: dict = {"person": person}
        if direction:
            params["direction"] = direction
        rows = await self.query(q_find, params)

        if not rows:
            return {"error": f"No open debt found for '{person}'"}

        # Multiple debts found — disambiguation needed
        if len(rows) > 1:
            options = []
            for i, r in enumerate(rows):
                options.append({
                    "index": i + 1,
                    "debt_id": r[0],
                    "current_amount": r[1],
                    "direction": r[2],
                    "person": r[3],
                    "original_amount": r[4],
                    "reason": r[5] or "",
                })
            return {"disambiguation_needed": True, "options": options}

        return await self._apply_debt_payment(rows[0], amount)

    async def apply_debt_payment_by_id(self, debt_id: int, amount: float) -> dict:
        """Apply payment to a specific debt by graph node ID."""
        q = """
        MATCH (d:Debt)-[:INVOLVES]->(p:Person)
        WHERE id(d) = $debt_id
        RETURN id(d), d.amount, d.direction, p.name, d.original_amount, d.reason
        """
        rows = await self.query(q, {"debt_id": debt_id})
        if not rows:
            return {"error": "Debt not found"}
        return await self._apply_debt_payment(rows[0], amount)

    async def _apply_debt_payment(self, row: list, amount: float) -> dict:
        """Internal: apply payment to a single debt row."""
        debt_id, current_amount, debt_dir, person_name, orig_amount, _reason = row
        if not orig_amount:
            orig_amount = current_amount

        remaining = current_amount - amount
        if remaining <= 0:
            q_update = """
            MATCH (d:Debt) WHERE id(d) = $debt_id
            SET d.amount = 0, d.status = 'paid', d.paid_at = $now,
                d.original_amount = $orig
            """
            await self.query(q_update, {"debt_id": debt_id, "now": _now(), "orig": orig_amount})
            return {
                "person": person_name,
                "paid": amount,
                "remaining": 0,
                "status": "paid",
                "direction": debt_dir,
            }
        else:
            q_update = """
            MATCH (d:Debt) WHERE id(d) = $debt_id
            SET d.amount = $remaining, d.status = 'partial',
                d.original_amount = $orig
            """
            await self.query(
                q_update, {"debt_id": debt_id, "remaining": remaining, "orig": orig_amount}
            )
            return {
                "person": person_name,
                "paid": amount,
                "remaining": remaining,
                "status": "partial",
                "direction": debt_dir,
            }

    async def create_expense_from_invoice(self, analysis: dict, file_hash: str) -> dict:
        """Auto-create Expense node from invoice analysis, link to File and vendor."""
        vendor = analysis.get("vendor", "Unknown")
        total = analysis.get("total_amount", 0)
        currency = analysis.get("currency", "SAR")
        date_str = analysis.get("date", _now()[:10])
        items = analysis.get("items", [])

        # Guess category from vendor/items
        item_names = " ".join(i.get("name", "") for i in items)
        category = self._guess_expense_category(vendor, item_names)

        desc = f"Invoice from {vendor}"
        if items:
            desc += f" ({len(items)} items)"

        # Create expense
        q = """
        CREATE (e:Expense {
            description: $desc, amount: $amount, currency: $currency,
            category: $category, date: $date, vendor: $vendor,
            source: 'invoice', file_hash: $file_hash, created_at: $now
        })
        """
        await self._graph.query(q, params={
            "desc": desc, "amount": total, "currency": currency,
            "category": category, "date": date_str, "vendor": vendor,
            "file_hash": file_hash, "now": _now(),
        })

        # Link to File node
        q_link = """
        MATCH (e:Expense {file_hash: $fh})
        MATCH (f:File {file_hash: $fh})
        MERGE (e)-[:FROM_INVOICE]->(f)
        """
        try:
            await self._graph.query(q_link, params={"fh": file_hash})
        except Exception as e:
            logger.debug("Invoice-expense link skipped: %s", e)

        # Upsert vendor as Company
        await self.upsert_company(vendor)
        # Link expense to vendor
        try:
            q_vendor = """
            MATCH (e:Expense {file_hash: $fh})
            MATCH (c:Company {name: $vendor})
            MERGE (e)-[:PAID_AT]->(c)
            """
            await self._graph.query(q_vendor, params={"fh": file_hash, "vendor": vendor})
        except Exception as e:
            logger.debug("Expense-vendor link skipped: %s", e)

        return {
            "description": desc,
            "amount": total,
            "currency": currency,
            "category": category,
            "vendor": vendor,
            "date": date_str,
        }

    @staticmethod
    def _guess_expense_category(vendor: str, items: str) -> str:
        """Simple keyword heuristic for expense category."""
        combined = f"{vendor} {items}".lower()
        rules = [
            (["restaurant", "مطعم", "food", "burger", "pizza", "coffee", "كافيه", "starbucks", "mcdonald"], "food"),
            (["grocery", "بقالة", "tamimi", "panda", "danube", "carrefour", "supermarket"], "groceries"),
            (["gas", "بنزين", "fuel", "petrol", "station"], "transport"),
            (["uber", "careem", "taxi"], "transport"),
            (["pharmacy", "صيدلية", "medicine", "medical", "hospital", "clinic", "doctor"], "health"),
            (["amazon", "noon", "jarir", "extra", "electronics"], "shopping"),
            (["stc", "mobily", "zain", "internet", "phone", "telecom"], "telecom"),
            (["rent", "إيجار", "electricity", "water", "كهرباء", "ماء"], "utilities"),
            (["school", "university", "course", "training", "book"], "education"),
        ]
        for keywords, category in rules:
            if any(kw in combined for kw in keywords):
                return category
        return "general"

    async def query_reminders(
        self, status: str | None = None, include_overdue: bool = True
    ) -> str:
        """Query reminders grouped by overdue/upcoming/snoozed with type/priority info."""
        now_str = _now()
        parts = []

        if include_overdue:
            q_overdue = """
            MATCH (r:Reminder)
            WHERE r.status = 'pending' AND r.due_date IS NOT NULL AND r.due_date < $now
            RETURN r.title, r.due_date, r.reminder_type, r.priority, r.snooze_count
            ORDER BY r.due_date
            LIMIT 20
            """
            rows = await self.query(q_overdue, {"now": now_str})
            if rows:
                parts.append("⚠ Overdue reminders:")
                for r in rows:
                    extra = self._format_reminder_tags(r[2], r[3], r[4])
                    parts.append(f"  - {r[0]} (due: {r[1]}){extra}")

        # Upcoming/pending
        filter_status = status or "pending"
        q_upcoming = """
        MATCH (r:Reminder {status: $status})
        WHERE r.due_date IS NULL OR r.due_date >= $now
        RETURN r.title, r.due_date, r.reminder_type, r.priority, r.snooze_count, r.description
        ORDER BY r.due_date
        LIMIT 20
        """
        rows = await self.query(q_upcoming, {"status": filter_status, "now": now_str})
        if rows:
            label = "Snoozed reminders:" if filter_status == "snoozed" else "Upcoming reminders:"
            parts.append(label)
            for r in rows:
                due = f" (due: {r[1]})" if r[1] else ""
                extra = self._format_reminder_tags(r[2], r[3], r[4])
                parts.append(f"  - {r[0]}{due}{extra}")

        return "\n".join(parts) if parts else "No reminders found."

    @staticmethod
    def _format_reminder_tags(
        reminder_type: str | None, priority: int | None, snooze_count: int | None
    ) -> str:
        tags = []
        if reminder_type and reminder_type != "one_time":
            tags.append(reminder_type)
        if priority and priority >= 3:
            tags.append(f"priority:{priority}")
        if snooze_count and snooze_count > 0:
            tags.append(f"snoozed:{snooze_count}x")
        return f" [{', '.join(tags)}]" if tags else ""

    # --- Daily Planner ---
    async def query_daily_plan(self) -> str:
        """Aggregate today's actionable items: overdue/today reminders, active tasks, debts I owe."""
        now_str = _now()
        today = now_str[:10]  # YYYY-MM-DD
        today_eod = today + "T23:59:59"
        parts = []

        # 1. Overdue + today's reminders
        q_reminders = """
        MATCH (r:Reminder)
        WHERE r.status = 'pending'
          AND r.due_date IS NOT NULL
          AND r.due_date <= $eod
        RETURN r.title, r.due_date, r.reminder_type, r.priority
        ORDER BY r.due_date
        LIMIT 20
        """
        rows = await self.query(q_reminders, {"eod": today_eod})
        if rows:
            parts.append("Reminders (overdue + today):")
            for r in rows:
                due = f" (due: {r[1]})" if r[1] else ""
                priority_tag = f" [priority:{r[3]}]" if r[3] and r[3] >= 3 else ""
                parts.append(f"  - {r[0]}{due}{priority_tag}")

        # 2. Active tasks sorted by priority
        q_tasks = """
        MATCH (t:Task)
        WHERE t.status IN ['todo', 'in_progress']
        OPTIONAL MATCH (t)-[:BELONGS_TO]->(p:Project)
        RETURN t.title, t.status, t.due_date, t.priority, p.name
        ORDER BY t.priority DESC, t.due_date
        LIMIT 20
        """
        rows = await self.query(q_tasks)
        if rows:
            parts.append("\nActive tasks:")
            for r in rows:
                status_tag = f" [{r[1]}]" if r[1] != "todo" else ""
                due = f" (due: {r[2]})" if r[2] else ""
                project = f" @ {r[4]}" if r[4] else ""
                parts.append(f"  - {r[0]}{status_tag}{due}{project}")

        # 3. Outstanding debts (I owe)
        q_debts = """
        MATCH (d:Debt)-[:INVOLVES]->(p:Person)
        WHERE d.status IN ['open', 'partial'] AND d.direction = 'i_owe'
        RETURN p.name, d.amount, d.reason
        ORDER BY d.amount DESC
        LIMIT 10
        """
        rows = await self.query(q_debts)
        if rows:
            parts.append("\nDebts I owe:")
            for r in rows:
                reason = f" ({r[2]})" if r[2] else ""
                parts.append(f"  - {r[0]}: {r[1]:.0f} SAR{reason}")

        return "\n".join(parts) if parts else "No actionable items for today."

    # --- Projects Overview ---
    async def query_projects_overview(self, status_filter: str | None = None) -> str:
        """Projects with their linked tasks and progress."""
        filter_clause = "WHERE p.status = $status" if status_filter else ""
        q = f"""
        MATCH (p:Project)
        {filter_clause}
        OPTIONAL MATCH (t:Task)-[:BELONGS_TO]->(p)
        RETURN p.name, p.status, p.description, p.priority,
               count(t) as total_tasks,
               sum(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) as done_tasks
        ORDER BY p.priority DESC, p.name
        LIMIT 30
        """
        params = {"status": status_filter} if status_filter else {}
        rows = await self.query(q, params)
        if not rows:
            label = f" with status '{status_filter}'" if status_filter else ""
            return f"No projects found{label}."

        parts = ["Projects:"]
        for r in rows:
            name, status, desc, priority, total, done = r
            progress = f" ({done}/{total} tasks done)" if total and total > 0 else ""
            priority_tag = f" [priority:{priority}]" if priority else ""
            status_tag = f" [{status}]" if status else ""
            parts.append(f"  - {name}{status_tag}{priority_tag}{progress}")
            if desc:
                parts.append(f"    {desc[:100]}")
        return "\n".join(parts)

    # --- Knowledge ---
    async def query_knowledge(self, topic: str | None = None) -> str:
        """Query Knowledge nodes, optionally filtering by topic."""
        if topic:
            q = """
            MATCH (k:Knowledge)
            WHERE toLower(k.title) CONTAINS toLower($topic)
               OR toLower(k.content) CONTAINS toLower($topic)
               OR toLower(k.category) CONTAINS toLower($topic)
            RETURN k.title, k.content, k.category, k.source
            LIMIT 20
            """
            rows = await self.query(q, {"topic": topic})
        else:
            q = """
            MATCH (k:Knowledge)
            RETURN k.title, k.content, k.category, k.source
            ORDER BY k.created_at DESC
            LIMIT 20
            """
            rows = await self.query(q)

        if not rows:
            label = f" about '{topic}'" if topic else ""
            return f"No knowledge entries found{label}."

        parts = ["Knowledge:"]
        for r in rows:
            title, content, category, source = r
            cat_tag = f" [{category}]" if category else ""
            src_tag = f" (source: {source})" if source else ""
            parts.append(f"  - {title}{cat_tag}{src_tag}")
            if content:
                preview = content[:150] + "..." if len(content) > 150 else content
                parts.append(f"    {preview}")
        return "\n".join(parts)

    # --- Active Tasks ---
    async def query_active_tasks(self, status_filter: str | None = None) -> str:
        """Tasks with optional status filter and project links."""
        if status_filter:
            filter_clause = "WHERE t.status = $status"
        else:
            filter_clause = "WHERE t.status IN ['todo', 'in_progress']"
        q = f"""
        MATCH (t:Task)
        {filter_clause}
        OPTIONAL MATCH (t)-[:BELONGS_TO]->(p:Project)
        RETURN t.title, t.status, t.due_date, t.priority, p.name
        ORDER BY t.priority DESC, t.due_date
        LIMIT 30
        """
        params = {"status": status_filter} if status_filter else {}
        rows = await self.query(q, params)
        if not rows:
            label = f" with status '{status_filter}'" if status_filter else ""
            return f"No active tasks found{label}."

        parts = ["Tasks:"]
        for r in rows:
            title, status, due_date, priority, project = r
            status_tag = f" [{status}]"
            due = f" (due: {due_date})" if due_date else ""
            proj = f" @ {project}" if project else ""
            prio = f" [priority:{priority}]" if priority else ""
            parts.append(f"  - {title}{status_tag}{prio}{due}{proj}")
        return "\n".join(parts)

    async def search_nodes(self, text: str, limit: int = 10) -> str:
        text_lower = text.lower()
        q = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS $text
           OR toLower(n.title) CONTAINS $text
           OR toLower(n.description) CONTAINS $text
        RETURN labels(n)[0] as label, coalesce(n.name, n.title) as name, n
        LIMIT $limit
        """
        rows = await self.query(q, {"text": text_lower, "limit": limit})
        if not rows:
            return ""
        parts = ["Graph search results:"]
        for r in rows:
            parts.append(f"  [{r[0]}] {r[1]}")
        return "\n".join(parts)

    async def _detect_similar_ideas(self, title: str, description: str = "") -> None:
        """Embed idea text into Qdrant and create SIMILAR_TO edges for similar ideas."""
        if not self._vector_service:
            return
        try:
            idea_text = f"{title}. {description}" if description else title
            # Upsert the idea into the vector store with entity_type metadata
            await self._vector_service.upsert_chunks(
                [idea_text],
                [{"source_type": "entity", "entity_type": "Idea", "entity_name": title}],
            )
            # Search for similar ideas (exclude exact match by checking title)
            results = await self._vector_service.search(
                idea_text, limit=5, entity_type="Idea"
            )
            for r in results:
                other_title = r["metadata"].get("entity_name", "")
                score = r["score"]
                if other_title and other_title != title and score >= 0.7:
                    try:
                        await self.create_relationship(
                            "Idea", "title", title,
                            "SIMILAR_TO",
                            "Idea", "title", other_title,
                        )
                        logger.info("Linked similar ideas: '%s' <-> '%s' (%.2f)", title, other_title, score)
                    except Exception as e:
                        logger.debug("Similar idea link skipped: %s", e)
        except Exception as e:
            logger.warning("Idea similarity detection failed: %s", e)

    # --- Inventory ---
    async def upsert_item(self, name: str, **props) -> dict:
        """Create or update an inventory Item node. If location provided, link to Location node."""
        location = props.pop("location", None)
        if location:
            location = self._normalize_location(location)
        file_hash = props.pop("file_hash", None)
        quantity = props.pop("quantity", 1)
        if quantity is None:
            quantity = 1

        # Filter None values and sanitize for FalkorDB
        filtered = {}
        for k, v in props.items():
            if v is None:
                continue
            if isinstance(v, dict):
                filtered[k] = str(v)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                filtered[k] = [str(i) for i in v]
            else:
                filtered[k] = v

        props_set = ", ".join(f"i.{k} = ${k}" for k in filtered)
        on_create_extra = f", {props_set}" if props_set else ""
        on_match_extra = f", {props_set}" if props_set else ""

        q = f"""
        MERGE (i:Item {{name: $name}})
        ON CREATE SET i.created_at = $now, i.quantity = $quantity, i.status = 'active'{on_create_extra}
        ON MATCH SET i.updated_at = $now, i.quantity = i.quantity + $quantity{on_match_extra}
        RETURN i.name, i.quantity, i.status
        """
        rows = await self.query(q, {"name": name, "now": _now(), "quantity": quantity, **filtered})

        result = {"name": name, "quantity": quantity, "status": "active"}
        if rows:
            result = {"name": rows[0][0], "quantity": rows[0][1], "status": rows[0][2] or "active"}

        # Link to Location
        if location:
            await self.upsert_location(location)
            q_loc = """
            MATCH (i:Item {name: $name})
            MATCH (l:Location {path: $location})
            MERGE (i)-[:STORED_IN]->(l)
            """
            await self.query(q_loc, {"name": name, "location": location})
            result["location"] = location

        # Link to File if file_hash provided
        if file_hash:
            try:
                q_file = """
                MATCH (i:Item {name: $name})
                MATCH (f:File {file_hash: $fh})
                MERGE (i)-[:FROM_PHOTO]->(f)
                """
                await self.query(q_file, {"name": name, "fh": file_hash})
            except Exception as e:
                logger.debug("Item-File link skipped: %s", e)

        return result

    async def upsert_location(self, path: str) -> None:
        """Create a Location node if it doesn't exist."""
        q = "MERGE (l:Location {path: $path}) ON CREATE SET l.created_at = $now"
        await self.query(q, {"path": path, "now": _now()})

    async def query_inventory(self, search: str | None = None, category: str | None = None) -> str:
        """Query inventory items, optionally filtered by search text or category."""
        conditions = ["i.status IN ['active', null]"]
        params: dict = {}

        if search:
            conditions.append("(toLower(i.name) CONTAINS $search OR toLower(i.description) CONTAINS $search)")
            params["search"] = search.lower()
        if category:
            conditions.append("toLower(i.category) = $category")
            params["category"] = category.lower()

        where = " AND ".join(conditions)
        q = f"""
        MATCH (i:Item)
        WHERE {where}
        OPTIONAL MATCH (i)-[:STORED_IN]->(l:Location)
        RETURN i.name, i.quantity, i.category, i.condition, i.brand, i.description, l.path
        ORDER BY i.name
        LIMIT 50
        """
        rows = await self.query(q, params)

        if not rows:
            label = f" matching '{search}'" if search else ""
            return f"No inventory items found{label}."

        parts = ["Inventory items:"]
        for r in rows:
            name, qty, cat, cond, brand, desc, loc = r
            line = f"  - {name}"
            if qty and qty > 1:
                line += f" (x{int(qty)})"
            if brand:
                line += f" [{brand}]"
            if cat:
                line += f" ({cat})"
            if cond and cond != "unknown":
                line += f" — {cond}"
            if loc:
                line += f" @ {loc}"
            parts.append(line)
        return "\n".join(parts)

    async def query_inventory_summary(self) -> dict:
        """Returns inventory totals by category and location."""
        # Total items + quantity
        q_total = """
        MATCH (i:Item)
        WHERE i.status IN ['active', null]
        RETURN count(i) as total_items, sum(i.quantity) as total_quantity
        """
        total_rows = await self.query(q_total)
        total_items = total_rows[0][0] if total_rows else 0
        total_quantity = int(total_rows[0][1]) if total_rows else 0

        # By category
        q_cat = """
        MATCH (i:Item)
        WHERE i.status IN ['active', null]
        RETURN coalesce(i.category, 'uncategorized') as cat, count(i) as cnt, sum(i.quantity) as qty
        ORDER BY qty DESC
        """
        cat_rows = await self.query(q_cat)
        by_category = [
            {"category": r[0], "count": r[1], "quantity": int(r[2])}
            for r in (cat_rows or [])
        ]

        # By location
        q_loc = """
        MATCH (i:Item)-[:STORED_IN]->(l:Location)
        WHERE i.status IN ['active', null]
        RETURN l.path, count(i) as cnt
        ORDER BY cnt DESC
        """
        loc_rows = await self.query(q_loc)
        by_location = [
            {"location": r[0], "count": r[1]}
            for r in (loc_rows or [])
        ]

        return {
            "total_items": total_items,
            "total_quantity": total_quantity,
            "by_category": by_category,
            "by_location": by_location,
        }

    async def update_item(self, name: str, **props) -> dict:
        """Update an existing Item. Handles location changes by re-linking."""
        location = props.pop("location", None)
        if location:
            location = self._normalize_location(location)

        # Build SET clause for non-None props
        filtered = {k: v for k, v in props.items() if v is not None}
        filtered["updated_at"] = _now()
        sets = ", ".join(f"i.{k} = ${k}" for k in filtered)
        q = f"""
        MATCH (i:Item {{name: $name}})
        SET {sets}
        RETURN i.name, i.quantity, i.status
        """
        rows = await self.query(q, {"name": name, **filtered})
        if not rows:
            return {"error": f"Item '{name}' not found"}

        result = {"name": rows[0][0], "quantity": rows[0][1], "status": rows[0][2]}

        if location:
            # Delete old STORED_IN and create new
            q_del = """
            MATCH (i:Item {name: $name})-[r:STORED_IN]->()
            DELETE r
            """
            await self.query(q_del, {"name": name})
            await self.upsert_location(location)
            q_loc = """
            MATCH (i:Item {name: $name})
            MATCH (l:Location {path: $location})
            MERGE (i)-[:STORED_IN]->(l)
            """
            await self.query(q_loc, {"name": name, "location": location})
            result["location"] = location

        return result

    async def find_item_by_file_hash(self, file_hash: str) -> dict:
        """Find an Item linked to a File node via FROM_PHOTO relationship."""
        q = """
        MATCH (i:Item)-[:FROM_PHOTO]->(f:File {file_hash: $fh})
        OPTIONAL MATCH (i)-[:STORED_IN]->(l:Location)
        RETURN i.name, i.quantity, i.status, l.path
        LIMIT 1
        """
        rows = await self.query(q, {"fh": file_hash})
        if not rows:
            return {}
        return {
            "name": rows[0][0],
            "quantity": rows[0][1],
            "status": rows[0][2],
            "location": rows[0][3],
        }

    async def adjust_item_quantity(self, name: str, delta: int) -> dict:
        """Adjust item quantity by delta (negative = reduce). Clamp at 0."""
        q = """
        MATCH (i:Item)
        WHERE toLower(i.name) CONTAINS toLower($name)
        SET i.quantity = CASE
            WHEN i.quantity + $delta < 0 THEN 0
            ELSE i.quantity + $delta
        END,
        i.updated_at = $now
        RETURN i.name, i.quantity, i.status
        """
        rows = await self.query(q, {"name": name, "delta": delta, "now": _now()})
        if not rows:
            return {"error": f"Item '{name}' not found"}
        return {"name": rows[0][0], "quantity": int(rows[0][1]), "status": rows[0][2]}

    async def _create_generic(self, label: str, key_field: str, value: str, **props) -> None:
        extra = {}
        for k, v in props.items():
            if v is None:
                continue
            # FalkorDB only accepts primitives or arrays of primitives
            if isinstance(v, dict):
                extra[k] = str(v)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                extra[k] = [str(i) for i in v]
            else:
                extra[k] = v
        inline = ""
        if extra:
            inline = ", " + ", ".join(f"{k}: ${k}" for k in extra)
        q = f"CREATE (n:{label} {{{key_field}: $value, created_at: $now{inline}}})"
        await self._graph.query(q, params={"value": value, "now": _now(), **extra})

    def _build_set_clause(self, props: dict, var: str = "p") -> str:
        filtered = {k: v for k, v in props.items() if v is not None}
        if not filtered:
            return ""
        return ", " + ", ".join(f"{var}.{k} = ${k}" for k in filtered)

    def _format_graph_context(self, rows: list) -> str:
        if not rows:
            return ""
        seen = set()
        parts = []
        for row in rows:
            for item in row:
                if isinstance(item, str) and item and item not in seen:
                    seen.add(item)
            # Try to build a readable representation
            desc_parts = []
            if row[0]:  # main node
                node = row[0]
                if hasattr(node, "properties"):
                    desc_parts.append(str(node.properties))
            if row[1] and row[3]:  # rel1, n1
                n1 = row[3]
                n1_name = n1.properties.get("name", n1.properties.get("title", "")) if hasattr(n1, "properties") else str(n1)
                desc_parts.append(f"-[{row[1]}]-> [{row[2]}] {n1_name}")
            if row[4] and row[6]:  # rel2, n2
                n2 = row[6]
                n2_name = n2.properties.get("name", n2.properties.get("title", "")) if hasattr(n2, "properties") else str(n2)
                desc_parts.append(f"-[{row[4]}]-> [{row[5]}] {n2_name}")
            if desc_parts:
                line = " ".join(desc_parts)
                if line not in seen:
                    seen.add(line)
                    parts.append(line)
        return "\n".join(parts[:20])


def _now() -> str:
    return datetime.utcnow().isoformat()
