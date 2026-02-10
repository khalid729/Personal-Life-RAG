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
        sets = ""
        if extra:
            sets = ", " + ", ".join(f"r.{k} = ${k}" for k in extra)
        q = f"""
        CREATE (r:Reminder {{title: $title, status: 'pending', created_at: $now{sets}}})
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **extra})

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

    async def query_financial_summary(self) -> str:
        parts = []
        # Recent expenses
        q1 = "MATCH (e:Expense) RETURN e.description, e.amount, e.category, e.created_at ORDER BY e.created_at DESC LIMIT 20"
        rows = await self.query(q1)
        if rows:
            parts.append("Recent expenses:")
            for r in rows:
                parts.append(f"  - {r[0]}: {r[1]} SAR ({r[2] or 'uncategorized'})")

        # Open debts
        q2 = "MATCH (d:Debt {status: 'open'})-[:INVOLVES]->(p:Person) RETURN p.name, d.amount, d.direction"
        rows = await self.query(q2)
        if rows:
            parts.append("Open debts:")
            for r in rows:
                direction = "they owe me" if r[2] == "owed_to_me" else "I owe them"
                parts.append(f"  - {r[0]}: {r[1]} SAR ({direction})")

        return "\n".join(parts) if parts else "No financial data found."

    async def query_reminders(self, status: str = "pending") -> str:
        q = "MATCH (r:Reminder {status: $status}) RETURN r.title, r.due_date, r.description ORDER BY r.due_date LIMIT 20"
        rows = await self.query(q, {"status": status})
        if not rows:
            return "No reminders found."
        parts = ["Reminders:"]
        for r in rows:
            due = f" (due: {r[1]})" if r[1] else ""
            parts.append(f"  - {r[0]}{due}")
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
