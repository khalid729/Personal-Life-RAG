import calendar
import logging
from datetime import datetime

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
    async def upsert_debt(self, person_name: str, amount: float, direction: str, **props) -> None:
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

    # --- Task ---
    async def upsert_task(self, title: str, **props) -> None:
        props_str = self._build_set_clause(props)
        q = f"""
        MERGE (t:Task {{title: $title}})
        ON CREATE SET t.status = 'todo', t.created_at = $now {props_str}
        ON MATCH SET t.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **props})

    # --- Idea ---
    async def create_idea(self, title: str, **props) -> None:
        extra = {k: v for k, v in props.items() if v is not None}
        sets = ""
        if extra:
            sets = ", " + ", ".join(f"i.{k} = ${k}" for k in extra)
        q = f"""
        CREATE (i:Idea {{title: $title, created_at: $now{sets}}})
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **extra})

    # --- Company ---
    async def upsert_company(self, name: str, **props) -> None:
        props_str = self._build_set_clause(props)
        q = f"""
        MERGE (c:Company {{name: $name}})
        ON CREATE SET c.created_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Topic ---
    async def upsert_topic(self, name: str, **props) -> None:
        props_str = self._build_set_clause(props)
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

                if etype == "Expense":
                    amount = props.pop("amount", 0)
                    await self.create_expense(ename, amount, **props)
                    count += 1
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
        """Record a debt payment. Finds matching open/partial debt, updates amount/status."""
        # Find matching debt
        direction_clause = "AND d.direction = $direction" if direction else ""
        q_find = f"""
        MATCH (d:Debt)-[:INVOLVES]->(p:Person)
        WHERE toLower(p.name) CONTAINS toLower($person)
          AND d.status IN ['open', 'partial']
          {direction_clause}
        RETURN id(d) as debt_id, d.amount, d.direction, p.name, d.original_amount
        ORDER BY d.amount DESC
        LIMIT 1
        """
        params: dict = {"person": person}
        if direction:
            params["direction"] = direction
        rows = await self.query(q_find, params)

        if not rows:
            return {"error": f"No open debt found for '{person}'"}

        debt_id, current_amount, debt_dir, person_name, orig_amount = rows[0]
        if not orig_amount:
            orig_amount = current_amount

        remaining = current_amount - amount
        if remaining <= 0:
            # Fully paid
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
            # Partial payment
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

    async def _create_generic(self, label: str, key_field: str, value: str, **props) -> None:
        extra = {k: v for k, v in props.items() if v is not None}
        sets = ""
        if extra:
            sets = ", " + ", ".join(f"n.{k} = ${k}" for k in extra)
        q = f"CREATE (n:{label} {{{key_field}: $value, created_at: $now{sets}}})"
        await self._graph.query(q, params={"value": value, "now": _now(), **extra})

    def _build_set_clause(self, props: dict) -> str:
        filtered = {k: v for k, v in props.items() if v is not None}
        if not filtered:
            return ""
        parts = [f", n.{k} = ${k}" for k in filtered]
        return "".join(parts).replace("n.", "p.", 1) if len(parts) == 1 else "".join(parts)

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
