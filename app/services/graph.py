import asyncio
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
        self._resolution_cache: dict[tuple[str, str], str] = {}

    def set_vector_service(self, vector_service) -> None:
        """Allow graph service to use vector for idea similarity detection."""
        self._vector_service = vector_service

    async def resolve_entity_name(self, name: str, entity_type: str, label_key: str = "name") -> str:
        """Resolve entity name via vector similarity + graph fuzzy fallback."""
        if not self._vector_service or not name or not settings.entity_resolution_enabled:
            return name
        if entity_type in ("Expense", "Debt", "Reminder", "Item", "Idea", "Tag"):
            return name

        cache_key = (name, entity_type)
        if cache_key in self._resolution_cache:
            return self._resolution_cache[cache_key]

        thresholds = {
            "Person": settings.entity_resolution_person_threshold,
        }
        threshold = thresholds.get(entity_type, settings.entity_resolution_default_threshold)

        # Strategy 1: Vector similarity
        try:
            results = await self._vector_service.search(
                name, limit=10, entity_type=entity_type
            )
            found_self = False
            for r in results:
                other_name = r["metadata"].get("entity_name", "")
                score = r["score"]
                if other_name == name:
                    found_self = True
                    continue
                if other_name and score >= threshold:
                    logger.info(
                        "Entity resolved (vector): '%s' -> '%s' (%s, score=%.2f)",
                        name, other_name, entity_type, score,
                    )
                    self._resolution_cache[cache_key] = other_name
                    await self._store_alias(entity_type, label_key, other_name, name)
                    return other_name
        except Exception as e:
            found_self = False
            logger.debug("Entity resolution vector failed for '%s': %s", name, e)

        # Strategy 2: Graph fuzzy match (substring on name + aliases)
        if len(name) >= 3:
            canonical = await self._resolve_by_graph_contains(name, entity_type, label_key)
            if canonical:
                self._resolution_cache[cache_key] = canonical
                return canonical

        # No match — register for future vector resolution
        if not found_self:
            try:
                await self._vector_service.upsert_chunks(
                    [name],
                    [{"source_type": "entity", "entity_type": entity_type, "entity_name": name}],
                )
            except Exception:
                pass

        return name

    async def _resolve_by_graph_contains(
        self, name: str, entity_type: str, label_key: str = "name",
    ) -> str | None:
        """Fallback: find entity by substring match on name or aliases."""
        try:
            q = f"""
            MATCH (n:{entity_type})
            WHERE toLower(n.{label_key}) CONTAINS toLower($term)
               OR any(a IN coalesce(n.name_aliases, [])
                      WHERE toLower(a) CONTAINS toLower($term))
            RETURN n.{label_key}
            LIMIT 3
            """
            rows = await self.query(q, {"term": name})
            if len(rows) == 1:
                canonical = rows[0][0]
                logger.info(
                    "Entity resolved (graph CONTAINS): '%s' -> '%s' (%s)",
                    name, canonical, entity_type,
                )
                await self._store_alias(entity_type, label_key, canonical, name)
                return canonical
            elif len(rows) > 1:
                logger.debug(
                    "Entity resolution ambiguous for '%s': %s",
                    name, [r[0] for r in rows],
                )
        except Exception as e:
            logger.debug("Graph CONTAINS resolution failed for '%s': %s", name, e)
        return None

    async def _store_alias(self, label: str, key_field: str, canonical: str, alias: str) -> None:
        """Store alias on existing entity node's name_aliases list."""
        try:
            q = f"""
            MATCH (n:{label} {{{key_field}: $canonical}})
            SET n.name_aliases = CASE
                WHEN n.name_aliases IS NULL THEN [$alias]
                WHEN NOT $alias IN n.name_aliases THEN n.name_aliases + [$alias]
                ELSE n.name_aliases
            END
            """
            await self.query(q, {"canonical": canonical, "alias": alias})
        except Exception as e:
            logger.debug("Alias storage skipped: %s", e)

    async def resolve_entity_names_batch(self, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        """Batch-resolve entity names: one GPU embed, parallel Qdrant searches, one batch register."""
        if not self._vector_service or not settings.entity_resolution_enabled:
            return {p: p[0] for p in pairs}

        skip_types = {"Expense", "Debt", "Reminder", "Item", "Idea", "Tag"}
        # Filter to resolvable types, deduplicate, skip already-cached
        to_resolve: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for name, etype in pairs:
            key = (name, etype)
            if etype in skip_types or not name or key in self._resolution_cache or key in seen:
                continue
            to_resolve.append(key)
            seen.add(key)

        if not to_resolve:
            return {p: self._resolution_cache.get(p, p[0]) for p in pairs}

        # 1. Batch embed all names at once
        names = [name for name, _ in to_resolve]
        vectors = self._vector_service.embed(names)
        logger.info("Batch entity resolution: embedded %d names in one call", len(names))

        # 2. Parallel Qdrant searches
        thresholds = {"Person": settings.entity_resolution_person_threshold}
        default_threshold = settings.entity_resolution_default_threshold

        async def _search_one(idx: int) -> tuple[int, list[dict]]:
            name, etype = to_resolve[idx]
            results = await self._vector_service.search_by_vector(
                vectors[idx], limit=10, entity_type=etype,
            )
            return idx, results

        search_results = await asyncio.gather(*[_search_one(i) for i in range(len(to_resolve))])

        # 3. Process results: find matches, collect alias tasks and unmatched names
        alias_tasks = []
        new_names: list[str] = []
        new_meta: list[dict] = []

        for idx, results in search_results:
            name, etype = to_resolve[idx]
            threshold = thresholds.get(etype, default_threshold)
            resolved = name  # default: keep original
            found_self = False

            for r in results:
                other_name = r["metadata"].get("entity_name", "")
                score = r["score"]
                if other_name == name:
                    found_self = True
                    continue
                if other_name and score >= threshold:
                    logger.info(
                        "Entity resolved (batch): '%s' -> '%s' (%s, score=%.2f)",
                        name, other_name, etype, score,
                    )
                    resolved = other_name
                    alias_tasks.append(self._store_alias(etype, "name", other_name, name))
                    break

            self._resolution_cache[(name, etype)] = resolved

            if resolved == name and not found_self:
                # No match and not yet registered — register for future resolution
                new_names.append(name)
                new_meta.append({"source_type": "entity", "entity_type": etype, "entity_name": name})

        # 4. Parallel alias storage
        if alias_tasks:
            await asyncio.gather(*alias_tasks)

        # 5. Batch register unmatched names
        if new_names:
            # Build index map for O(1) vector lookup
            name_to_idx = {to_resolve[i][0]: i for i in range(len(to_resolve))}
            new_vectors = [vectors[name_to_idx[n]] for n in new_names]

            import uuid
            from qdrant_client.models import PointStruct
            points = []
            for i, (chunk, vec) in enumerate(zip(new_names, new_vectors)):
                meta = new_meta[i]
                payload = {
                    "text": chunk,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    **meta,
                }
                points.append(PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload))

            await self._vector_service._client.upsert(
                collection_name=settings.qdrant_collection,
                points=points,
            )
            logger.info("Batch registered %d new entity names", len(new_names))

        return {p: self._resolution_cache.get(p, p[0]) for p in pairs}

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
        name = await self.resolve_entity_name(name, "Person")
        # Auto-convert Hijri date_of_birth to Gregorian
        dob = props.get("date_of_birth", "")
        if dob:
            try:
                y, m, d = map(int, dob.split("-"))
                if y < 1900:  # Hijri year
                    from hijri_converter import Hijri
                    greg = Hijri(y, m, d).to_gregorian()
                    props["date_of_birth_hijri"] = dob
                    props["date_of_birth"] = greg.isoformat()
            except Exception:
                pass  # keep original
        props_str = self._build_set_clause(props)
        q = f"""
        MERGE (p:Person {{name: $name}})
        ON CREATE SET p.created_at = $now {props_str}
        ON MATCH SET p.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Project ---
    async def upsert_project(self, name: str, **props) -> None:
        name = await self.resolve_entity_name(name, "Project")
        props_str = self._build_set_clause(props)
        q = f"""
        MERGE (p:Project {{name: $name}})
        ON CREATE SET p.created_at = $now {props_str}
        ON MATCH SET p.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    async def delete_project(self, name: str) -> dict:
        """Delete a project and its linked tasks, sections, lists. Returns deleted info or error."""
        q = """
        MATCH (p:Project) WHERE toLower(p.name) CONTAINS toLower($name)
        OPTIONAL MATCH (t:Task)-[:BELONGS_TO]->(p)
        OPTIONAL MATCH (p)-[:HAS_SECTION]->(s:Section)
        OPTIONAL MATCH (l:List)-[:BELONGS_TO]->(p)
        OPTIONAL MATCH (l)-[:HAS_ENTRY]->(le:ListEntry)
        WITH p, p.name AS pname, collect(DISTINCT t) AS tasks,
             collect(DISTINCT t.title) AS task_titles,
             collect(DISTINCT s) AS sections,
             collect(DISTINCT l) AS lists,
             collect(DISTINCT le) AS list_entries
        DETACH DELETE p
        FOREACH (t IN tasks | DETACH DELETE t)
        FOREACH (s IN sections | DETACH DELETE s)
        FOREACH (l IN lists | DETACH DELETE l)
        FOREACH (le IN list_entries | DETACH DELETE le)
        RETURN pname, task_titles
        """
        rows = await self.query(q, {"name": name})
        if not rows:
            return {"error": f"No project found matching '{name}'"}
        pname = rows[0][0]
        task_titles = [t for t in (rows[0][1] or []) if t]
        return {"deleted": pname, "tasks_deleted": len(task_titles), "task_titles": task_titles}

    async def set_project_aliases(self, name: str, aliases: list[str]) -> None:
        """Set aliases on a project node (deduped via _store_alias)."""
        name = await self.resolve_entity_name(name, "Project")
        for alias in aliases:
            if alias and alias != name:
                await self._store_alias("Project", "name", name, alias)

    async def register_aliases_in_vector(
        self, canonical_name: str, aliases: list[str], entity_type: str = "Project",
    ) -> None:
        """Register each alias in vector store pointing to canonical_name."""
        if not self._vector_service:
            return
        for alias in aliases:
            if not alias or alias == canonical_name:
                continue
            try:
                await self._vector_service.upsert_chunks(
                    [alias],
                    [{"source_type": "entity", "entity_type": entity_type, "entity_name": canonical_name}],
                )
                logger.info("Alias vector registered: '%s' -> '%s' (%s)", alias, canonical_name, entity_type)
            except Exception as e:
                logger.debug("Alias vector registration failed for '%s': %s", alias, e)

    async def merge_projects(self, source_names: list[str], target_name: str) -> dict:
        """Merge source projects into target. Re-links tasks, deletes sources."""
        # Ensure target exists
        await self.upsert_project(target_name)
        tasks_moved = 0
        sources_deleted = 0

        for src in source_names:
            # Re-link tasks from source to target
            q_relink = """
            MATCH (t:Task)-[r:BELONGS_TO]->(src:Project)
            WHERE toLower(src.name) CONTAINS toLower($src_name)
            MATCH (tgt:Project {name: $target_name})
            DELETE r
            MERGE (t)-[:BELONGS_TO]->(tgt)
            RETURN count(t)
            """
            rows = await self.query(q_relink, {"src_name": src, "target_name": target_name})
            if rows and rows[0][0]:
                tasks_moved += rows[0][0]

            # Re-link sections from source to target
            q_sections = """
            MATCH (src:Project)-[r:HAS_SECTION]->(s:Section)
            WHERE toLower(src.name) CONTAINS toLower($src_name)
            MATCH (tgt:Project {name: $target_name})
            DELETE r
            MERGE (tgt)-[:HAS_SECTION]->(s)
            RETURN count(s)
            """
            await self.query(q_sections, {"src_name": src, "target_name": target_name})

            # Re-link lists from source to target
            q_lists = """
            MATCH (l:List)-[r:BELONGS_TO]->(src:Project)
            WHERE toLower(src.name) CONTAINS toLower($src_name)
            MATCH (tgt:Project {name: $target_name})
            DELETE r
            MERGE (l)-[:BELONGS_TO]->(tgt)
            RETURN count(l)
            """
            await self.query(q_lists, {"src_name": src, "target_name": target_name})

            # Delete source project node
            q_del = """
            MATCH (p:Project) WHERE toLower(p.name) CONTAINS toLower($src_name)
            AND p.name <> $target_name
            DETACH DELETE p
            RETURN count(p)
            """
            del_rows = await self.query(q_del, {"src_name": src, "target_name": target_name})
            if del_rows and del_rows[0][0]:
                sources_deleted += del_rows[0][0]

        return {"target": target_name, "sources_deleted": sources_deleted, "tasks_moved": tasks_moved}

    # --- Sections ---

    async def create_section(self, project_name: str, section_name: str, **props) -> dict:
        project_name = await self.resolve_entity_name(project_name, "Project")
        filtered = {k: v for k, v in props.items() if v is not None and v != ""}
        inline = ""
        if filtered:
            inline = ", " + ", ".join(f"{k}: ${k}" for k in filtered)
        q = f"""
        MATCH (p:Project {{name: $pname}})
        CREATE (s:Section {{name: $sname, created_at: $now{inline}}})
        CREATE (p)-[:HAS_SECTION]->(s)
        RETURN s.name
        """
        rows = await self.query(q, {"pname": project_name, "sname": section_name, "now": _now(), **filtered})
        if not rows:
            return {"error": f"Project '{project_name}' not found"}
        return {"status": "created", "section": section_name, "project": project_name}

    async def update_section(self, project_name: str, section_name: str, **props) -> dict:
        project_name = await self.resolve_entity_name(project_name, "Project")
        props_str = self._build_set_clause(props, var="s")
        if not props_str:
            return {"error": "No fields to update"}
        q = f"""
        MATCH (p:Project {{name: $pname}})-[:HAS_SECTION]->(s:Section {{name: $sname}})
        SET s.updated_at = $now {props_str}
        RETURN s.name
        """
        rows = await self.query(q, {"pname": project_name, "sname": section_name, "now": _now(), **{k: v for k, v in props.items() if v is not None and v != ""}})
        if not rows:
            return {"error": f"Section '{section_name}' not found in project '{project_name}'"}
        return {"status": "updated", "section": section_name}

    async def delete_section(self, project_name: str, section_name: str) -> dict:
        project_name = await self.resolve_entity_name(project_name, "Project")
        q = """
        MATCH (p:Project {name: $pname})-[:HAS_SECTION]->(s:Section {name: $sname})
        OPTIONAL MATCH (e)-[r:IN_SECTION]->(s)
        DELETE r
        DETACH DELETE s
        RETURN p.name
        """
        rows = await self.query(q, {"pname": project_name, "sname": section_name})
        if not rows:
            return {"error": f"Section '{section_name}' not found in project '{project_name}'"}
        return {"status": "deleted", "section": section_name}

    async def assign_to_section(self, project_name: str, section_name: str,
                                entity_type: str, entity_name: str) -> dict:
        """Link an existing entity to a section via IN_SECTION."""
        project_name = await self.resolve_entity_name(project_name, "Project")
        key_field = "name" if entity_type not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
        q = f"""
        MATCH (p:Project {{name: $pname}})-[:HAS_SECTION]->(s:Section {{name: $sname}})
        MATCH (e:{entity_type} {{{key_field}: $ename}})
        MERGE (e)-[:IN_SECTION]->(s)
        RETURN e.{key_field}
        """
        rows = await self.query(q, {"pname": project_name, "sname": section_name, "ename": entity_name})
        if not rows:
            return {"error": f"Could not link {entity_type} '{entity_name}' to section '{section_name}'"}
        return {"status": "assigned", "entity": entity_name, "section": section_name}

    async def create_project_with_phases(self, name: str, **props) -> dict:
        """Create a project and its default phase sections."""
        await self.upsert_project(name, **props)
        for i, phase in enumerate(self._DEFAULT_PHASES):
            await self.create_section(name, phase, section_type="phase", order=i + 1)
        q = """
        MATCH (p:Project {name: $name})
        SET p.active_phase = $phase
        """
        await self._graph.query(q, params={"name": name, "phase": self._DEFAULT_PHASES[0]})
        return {"status": "created", "name": name, "phases": self._DEFAULT_PHASES}

    async def set_active_phase(self, project_name: str, phase_name: str) -> dict:
        project_name = await self.resolve_entity_name(project_name, "Project")
        q = """
        MATCH (p:Project {name: $pname})-[:HAS_SECTION]->(s:Section {name: $sname})
        WHERE s.section_type = 'phase'
        SET p.active_phase = $sname
        RETURN p.name
        """
        rows = await self.query(q, {"pname": project_name, "sname": phase_name})
        if not rows:
            return {"error": f"Phase '{phase_name}' not found in project '{project_name}'"}
        return {"status": "updated", "project": project_name, "active_phase": phase_name}

    # --- Lists ---

    async def create_list(self, name: str, list_type: str = "checklist",
                          project_name: str | None = None, section_name: str | None = None) -> dict:
        filtered = {"list_type": list_type}
        inline = ", list_type: $list_type"
        q = f"CREATE (l:List {{name: $name, created_at: $now{inline}}}) RETURN l.name"
        await self._graph.query(q, params={"name": name, "now": _now(), **filtered})

        if project_name:
            project_name = await self.resolve_entity_name(project_name, "Project")
            await self.create_relationship("List", "name", name, "BELONGS_TO", "Project", "name", project_name)
        if section_name and project_name:
            try:
                await self.assign_to_section(project_name, section_name, "List", name)
            except Exception:
                pass
        return {"status": "created", "name": name, "list_type": list_type}

    async def add_list_entry(self, list_name: str, content: str) -> dict:
        q = """
        MATCH (l:List {name: $lname})
        CREATE (e:ListEntry {content: $content, checked: false, added_at: $now})
        CREATE (l)-[:HAS_ENTRY]->(e)
        RETURN e.content
        """
        rows = await self.query(q, {"lname": list_name, "content": content, "now": _now()})
        if not rows:
            return {"error": f"List '{list_name}' not found"}
        return {"status": "added", "list": list_name, "entry": content}

    async def check_list_entry(self, list_name: str, content: str, checked: bool = True) -> dict:
        q = """
        MATCH (l:List {name: $lname})-[:HAS_ENTRY]->(e:ListEntry)
        WHERE toLower(e.content) CONTAINS toLower($content)
        SET e.checked = $checked, e.checked_at = $now
        RETURN e.content
        """
        rows = await self.query(q, {"lname": list_name, "content": content, "checked": checked, "now": _now()})
        if not rows:
            return {"error": f"Entry '{content}' not found in list '{list_name}'"}
        return {"status": "checked" if checked else "unchecked", "entry": rows[0][0]}

    async def remove_list_entry(self, list_name: str, content: str) -> dict:
        q = """
        MATCH (l:List {name: $lname})-[:HAS_ENTRY]->(e:ListEntry)
        WHERE toLower(e.content) CONTAINS toLower($content)
        DETACH DELETE e
        RETURN l.name
        """
        rows = await self.query(q, {"lname": list_name, "content": content})
        if not rows:
            return {"error": f"Entry '{content}' not found in list '{list_name}'"}
        return {"status": "removed", "list": list_name, "entry": content}

    async def query_list(self, list_name: str) -> str:
        q = """
        MATCH (l:List {name: $lname})
        OPTIONAL MATCH (l)-[:HAS_ENTRY]->(e:ListEntry)
        RETURN l, collect({content: e.content, checked: e.checked, added_at: e.added_at})
        """
        rows = await self.query(q, {"lname": list_name})
        if not rows:
            return f"List '{list_name}' not found."
        node_props = rows[0][0].properties if hasattr(rows[0][0], "properties") else rows[0][0]
        entries = [e for e in (rows[0][1] or []) if e.get("content")]

        parts = [f"List: {node_props.get('name')} ({node_props.get('list_type', 'checklist')})"]
        if entries:
            for e in entries:
                mark = "x" if e.get("checked") else " "
                parts.append(f"  [{mark}] {e['content']}")
        else:
            parts.append("  (empty)")
        return "\n".join(parts)

    async def query_lists_overview(self, project_name: str | None = None) -> str:
        if project_name:
            project_name = await self.resolve_entity_name(project_name, "Project")
            q = """
            MATCH (l:List)-[:BELONGS_TO]->(p:Project {name: $pname})
            OPTIONAL MATCH (l)-[:HAS_ENTRY]->(e:ListEntry)
            RETURN l.name, l.list_type, count(e), sum(CASE WHEN e.checked = true THEN 1 ELSE 0 END)
            """
            rows = await self.query(q, {"pname": project_name})
        else:
            q = """
            MATCH (l:List)
            OPTIONAL MATCH (l)-[:HAS_ENTRY]->(e:ListEntry)
            RETURN l.name, l.list_type, count(e), sum(CASE WHEN e.checked = true THEN 1 ELSE 0 END)
            LIMIT 30
            """
            rows = await self.query(q)

        if not rows:
            return "No lists found."
        parts = ["Lists:"]
        for r in rows:
            name, ltype, total, checked = r
            total = total or 0
            checked = checked or 0
            progress = f" ({checked}/{total} checked)" if total > 0 else ""
            parts.append(f"  - {name} [{ltype}]{progress}")
        return "\n".join(parts)

    async def delete_list(self, list_name: str) -> dict:
        # Delete entries first, then the list node
        q_entries = """
        MATCH (l:List {name: $name})-[:HAS_ENTRY]->(e:ListEntry)
        DETACH DELETE e
        RETURN count(e)
        """
        await self.query(q_entries, {"name": list_name})
        q = """
        MATCH (l:List {name: $name})
        DETACH DELETE l
        RETURN $name
        """
        rows = await self.query(q, {"name": list_name})
        if not rows:
            return {"error": f"List '{list_name}' not found"}
        return {"status": "deleted", "name": list_name}

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

    # --- Category normalization ---
    _CATEGORY_ALIASES: dict[str, str] = {
        # Electronics
        "electronics": "إلكترونيات",
        "electronic": "إلكترونيات",
        "cables": "إلكترونيات",
        "cable": "إلكترونيات",
        "كيابل": "إلكترونيات",
        "شواحن": "إلكترونيات",
        "chargers": "إلكترونيات",
        "batteries": "إلكترونيات",
        "بطاريات": "إلكترونيات",
        # Tools
        "tools": "أدوات",
        "tool": "أدوات",
        "عدة": "أدوات",
        "عدد": "أدوات",
        # Parts
        "parts": "قطع غيار",
        "spare parts": "قطع غيار",
        # Household
        "household": "منزلية",
        "home": "منزلية",
        "منزلي": "منزلية",
        # Accessories
        "accessories": "إكسسوارات",
        "accessory": "إكسسوارات",
        # Stationery
        "stationery": "قرطاسية",
        "office supplies": "قرطاسية",
        # Chemicals
        "chemicals": "كيماويات",
        "chemical": "كيماويات",
    }

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Normalize category to consistent Arabic form."""
        if not category:
            return ""
        cat = category.strip()
        lower = cat.lower()
        if lower in GraphService._CATEGORY_ALIASES:
            return GraphService._CATEGORY_ALIASES[lower]
        return cat

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
            sets = ", " + ", ".join(f"r.{k} = ${k}" for k in extra)

        # Case-insensitive match existing pending/snoozed (FalkorDB can't do case-insensitive MERGE)
        q_match = f"""
        MATCH (r:Reminder)
        WHERE toLower(r.title) = toLower($title)
          AND r.status IN ['pending', 'snoozed']
        SET r.updated_at = $now{sets}
        RETURN r.title
        """
        params = {"title": title, "now": _now(), **extra}
        rows = await self.query(q_match, params)
        if rows:
            return  # Updated existing reminder

        # No match — create new
        q_create = f"""
        CREATE (r:Reminder {{title: $title}})
        SET r.status = 'pending', r.created_at = $now, r.snooze_count = 0{sets}
        """
        await self._graph.query(q_create, params=params)

    async def _find_matching_reminders(self, title: str, status_filter: str = "") -> list:
        """Find reminders matching title using multi-strategy search.

        Strategies (in order):
        1. Direct CONTAINS (original title)
        2. CONTAINS with singular/plural variant
        3. All-keywords match (every word in title found in reminder)
        4. Vector similarity (fuzzy match for transliteration variants)
        """
        status_clause = ""
        if status_filter:
            status_clause = f" AND r.status IN {status_filter}"

        # Strategy 1: direct CONTAINS
        q = f"""
        MATCH (r:Reminder) WHERE toLower(r.title) CONTAINS toLower($title){status_clause}
        RETURN r.title, id(r)
        """
        rows = await self.query(q, {"title": title})
        if rows:
            return rows

        # Strategy 2: singular/plural variant
        t = title.strip()
        variant = t[:-1] if (t.endswith("s") and len(t) > 3) else t + "s"
        rows = await self.query(q, {"title": variant})
        if rows:
            logger.info("Reminder matched with variant '%s' (original: '%s')", variant, title)
            return rows

        # Strategy 3: all-keywords — each word must appear in the title
        words = [w for w in title.lower().split() if len(w) >= 3]
        if len(words) >= 2:
            conditions = " AND ".join(f"toLower(r.title) CONTAINS '{w}'" for w in words)
            q_kw = f"""
            MATCH (r:Reminder) WHERE {conditions}{status_clause}
            RETURN r.title, id(r)
            """
            rows = await self.query(q_kw, {})
            if rows:
                logger.info("Reminder matched via keywords %s (original: '%s')", words, title)
                return rows

        # Strategy 3.5: reverse CONTAINS — search query contains the stored title
        # Handles cases where user passes long text like "تحقق من التواريخ الهجرية (متأخرة)"
        # and the stored title is a substring of that query
        q_rev = f"""
        MATCH (r:Reminder) WHERE toLower($title) CONTAINS toLower(r.title){status_clause}
        RETURN r.title, id(r)
        """
        rows = await self.query(q_rev, {"title": title})
        if rows:
            logger.info("Reminder matched via reverse CONTAINS (original: '%s')", title)
            return rows

        # Strategy 4: vector similarity (handles transliteration/translation variants)
        if self._vector_service:
            try:
                resolved = await self.resolve_entity_name(title, "Reminder")
                if resolved and resolved.lower() != title.lower():
                    rows = await self.query(q, {"title": resolved})
                    if rows:
                        logger.info("Reminder matched via vector similarity '%s' (original: '%s')", resolved, title)
                        return rows
            except Exception:
                pass

        return []

    async def update_reminder_status(
        self, title: str, action: str, snooze_until: str | None = None
    ) -> dict:
        """Mark reminder done/snoozed/cancelled. Returns updated info."""
        # Find matching reminders first
        matches = await self._find_matching_reminders(title)
        if not matches:
            return {"error": f"No reminder found matching '{title}'"}

        # Apply action to all matches
        matched_titles = [r[0] for r in matches]
        for r_title in matched_titles:
            if action == "done":
                q = """
                MATCH (r:Reminder) WHERE r.title = $title
                SET r.status = 'done', r.completed_at = $now
                RETURN r.title, r.status
                """
                await self.query(q, {"title": r_title, "now": _now()})
            elif action == "snooze":
                q = """
                MATCH (r:Reminder) WHERE r.title = $title
                SET r.status = 'snoozed',
                    r.snooze_count = coalesce(r.snooze_count, 0) + 1,
                    r.snoozed_until = $snooze_until
                RETURN r.title, r.status, r.snooze_count
                """
                await self.query(q, {"title": r_title, "snooze_until": snooze_until or ""})
            elif action == "cancel":
                q = """
                MATCH (r:Reminder) WHERE r.title = $title
                SET r.status = 'cancelled', r.cancelled_at = $now
                RETURN r.title, r.status
                """
                await self.query(q, {"title": r_title, "now": _now()})
            elif action == "delete":
                q = """
                MATCH (r:Reminder) WHERE r.title = $title
                DETACH DELETE r
                RETURN $title AS deleted
                """
                await self.query(q, {"title": r_title})
            else:
                return {"error": f"Unknown action: {action}"}

        return {"title": matched_titles[0], "status": action if action != "done" else "done"}

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
        SET r.due_date = $next_due, r.updated_at = $now, r.notified_at = NULL
        """
        await self.query(q_update, {"title": title, "next_due": next_due_str, "now": _now()})

        return {"title": r_title, "next_due": next_due_str, "recurrence": recurrence}

    async def delete_reminder(self, title: str) -> dict:
        """Delete a reminder by title (fuzzy match). Returns deleted title or error."""
        q = """
        MATCH (r:Reminder) WHERE toLower(r.title) CONTAINS toLower($title)
        WITH r, r.title AS t
        DETACH DELETE r
        RETURN t
        """
        rows = await self.query(q, {"title": title})
        if not rows:
            return {"error": f"No reminder found matching '{title}'"}
        deleted = [r[0] for r in rows]
        return {"deleted": deleted, "count": len(deleted)}

    async def delete_reminder_by_id(self, node_id: int) -> dict:
        """Delete a specific reminder by its internal node ID."""
        q = """
        MATCH (r:Reminder) WHERE ID(r) = $nid
        WITH r, r.title AS t
        DETACH DELETE r
        RETURN t
        """
        rows = await self.query(q, {"nid": node_id})
        if not rows:
            return {"error": f"No reminder found with ID {node_id}"}
        return {"deleted": rows[0][0], "id": node_id}

    async def update_reminder(
        self, title: str, new_title: str | None = None,
        due_date: str | None = None, priority: int | None = None,
        description: str | None = None, recurrence: str | None = None,
    ) -> dict:
        """Update reminder properties by title (fuzzy match)."""
        sets = []
        params: dict = {"title": title, "now": _now()}
        if new_title is not None:
            sets.append("r.title = $new_title")
            params["new_title"] = new_title
        if due_date is not None:
            sets.append("r.due_date = $due_date")
            params["due_date"] = due_date
        if priority is not None:
            sets.append("r.priority = $priority")
            params["priority"] = priority
        if description is not None:
            sets.append("r.description = $description")
            params["description"] = description
        if recurrence is not None:
            sets.append("r.recurrence = $recurrence")
            params["recurrence"] = recurrence
        if not sets:
            return {"error": "No fields to update"}
        sets.append("r.updated_at = $now")
        q = f"""
        MATCH (r:Reminder) WHERE toLower(r.title) CONTAINS toLower($title)
        SET {', '.join(sets)}
        RETURN r.title, r.status, r.due_date
        """
        rows = await self.query(q, params)
        if not rows:
            return {"error": f"No reminder found matching '{title}'"}
        return {"title": rows[0][0], "status": rows[0][1], "due_date": rows[0][2]}

    async def merge_duplicate_reminders(self) -> dict:
        """Find and merge duplicate reminders. Keeps the one with earliest due_date or lowest ID.
        Returns list of merge groups and total removed count."""
        # Step 1: Find all pending/snoozed reminders
        q_all = """
        MATCH (r:Reminder)
        WHERE r.status IN ['pending', 'snoozed']
        RETURN ID(r) AS id, r.title, r.due_date, r.priority, r.reminder_type,
               r.recurrence, r.status, r.snooze_count, r.description
        ORDER BY r.title
        """
        rows = await self.query(q_all, {})
        if not rows:
            return {"merged_groups": [], "total_removed": 0}

        # Step 2: Group by normalized title (lowercase, stripped)
        from collections import defaultdict
        groups: dict[str, list] = defaultdict(list)
        for row in rows:
            nid, title = row[0], row[1]
            key = title.strip().lower()
            groups[key].append({
                "id": nid, "title": title, "due_date": row[2],
                "priority": row[3], "reminder_type": row[4],
                "recurrence": row[5], "status": row[6],
                "snooze_count": row[7], "description": row[8],
            })

        merged_groups = []
        total_removed = 0

        for key, items in groups.items():
            if len(items) < 2:
                continue
            # Keep the one with: pending > snoozed, earliest due_date, then lowest ID
            def sort_key(item):
                status_rank = 0 if item["status"] == "pending" else 1
                due = item["due_date"] or "9999"
                return (status_rank, due, item["id"])
            items.sort(key=sort_key)
            keep = items[0]
            remove = items[1:]

            # Merge best properties into keeper
            best_priority = keep.get("priority") or 0
            best_recurrence = keep.get("recurrence")
            best_description = keep.get("description")
            for item in remove:
                if (item.get("priority") or 0) > best_priority:
                    best_priority = item["priority"]
                if not best_recurrence and item.get("recurrence"):
                    best_recurrence = item["recurrence"]
                if not best_description and item.get("description"):
                    best_description = item["description"]

            # Update keeper with best properties
            update_sets = ["r.updated_at = $now"]
            update_params: dict = {"kid": keep["id"], "now": _now()}
            if best_priority and best_priority != (keep.get("priority") or 0):
                update_sets.append("r.priority = $priority")
                update_params["priority"] = best_priority
            if best_recurrence and best_recurrence != keep.get("recurrence"):
                update_sets.append("r.recurrence = $recurrence")
                update_params["recurrence"] = best_recurrence
            if best_description and best_description != keep.get("description"):
                update_sets.append("r.description = $description")
                update_params["description"] = best_description

            q_update = f"""
            MATCH (r:Reminder) WHERE ID(r) = $kid
            SET {', '.join(update_sets)}
            """
            await self.query(q_update, update_params)

            # Delete duplicates
            remove_ids = [item["id"] for item in remove]
            q_delete = """
            MATCH (r:Reminder) WHERE ID(r) IN $ids
            DETACH DELETE r
            """
            await self.query(q_delete, {"ids": remove_ids})

            merged_groups.append({
                "kept": keep["title"],
                "kept_id": keep["id"],
                "removed_count": len(remove),
                "removed_ids": remove_ids,
            })
            total_removed += len(remove)

        return {"merged_groups": merged_groups, "total_removed": total_removed}

    async def delete_all_reminders(self, status: str | None = None) -> dict:
        """Delete all reminders, optionally filtered by status. Returns count deleted."""
        if status:
            q = """
            MATCH (r:Reminder {status: $status})
            WITH r, r.title AS t
            DETACH DELETE r
            RETURN t
            """
            rows = await self.query(q, {"status": status})
        else:
            q = """
            MATCH (r:Reminder)
            WITH r, r.title AS t
            DETACH DELETE r
            RETURN t
            """
            rows = await self.query(q, {})
        return {"deleted_count": len(rows), "titles": [r[0] for r in rows]}

    # --- Task ---
    _ENERGY_ALIASES: dict[str, str] = {
        "high": "high", "عالي": "high", "عالية": "high", "deep": "high", "deep focus": "high",
        "medium": "medium", "متوسط": "medium", "متوسطة": "medium", "normal": "medium",
        "low": "low", "منخفض": "low", "منخفضة": "low", "easy": "low", "light": "low",
    }

    @staticmethod
    def _normalize_energy(level: str | None) -> str | None:
        if not level:
            return None
        return GraphService._ENERGY_ALIASES.get(level.lower().strip(), level.lower().strip())

    async def upsert_task(self, title: str, **props) -> None:
        if "energy_level" in props and props["energy_level"]:
            props["energy_level"] = self._normalize_energy(props["energy_level"])
        props_str = self._build_set_clause(props, var="t")
        q = f"""
        MERGE (t:Task {{title: $title}})
        ON CREATE SET t.status = 'todo', t.created_at = $now {props_str}
        ON MATCH SET t.updated_at = $now {props_str}
        """
        await self._graph.query(q, params={"title": title, "now": _now(), **props})

    async def delete_task(self, title: str) -> dict:
        """Delete a task by title (fuzzy match). Returns deleted title or error."""
        q = """
        MATCH (t:Task) WHERE toLower(t.title) CONTAINS toLower($title)
        WITH t, t.title AS tname
        DETACH DELETE t
        RETURN tname
        """
        rows = await self.query(q, {"title": title})
        if not rows:
            return {"error": f"No task found matching '{title}'"}
        deleted = [r[0] for r in rows]
        return {"deleted": deleted, "count": len(deleted)}

    async def _auto_dismiss_reminders(self, task_title: str) -> list[str]:
        """Auto-dismiss pending reminders matching a completed task title."""
        matches = await self._find_matching_reminders(task_title, status_filter="['pending']")
        if not matches:
            return []
        dismissed = []
        for r_title, _ in matches:
            q = """
            MATCH (r:Reminder) WHERE r.title = $title AND r.status = 'pending'
            SET r.status = 'done', r.completed_at = $now
            """
            await self.query(q, {"title": r_title, "now": _now()})
            dismissed.append(r_title)
        if dismissed:
            logger.info("Task '%s' done → auto-dismissed %d reminder(s): %s",
                        task_title, len(dismissed), dismissed)
        return dismissed

    async def update_task_direct(
        self, title: str, new_title: str | None = None,
        status: str | None = None, due_date: str | None = None,
        priority: int | None = None, project: str | None = None,
    ) -> dict:
        """Update task properties by title (fuzzy match)."""
        sets = []
        params: dict = {"title": title, "now": _now()}
        if new_title is not None:
            sets.append("t.title = $new_title")
            params["new_title"] = new_title
        if status is not None:
            sets.append("t.status = $status")
            params["status"] = status
        if due_date is not None:
            sets.append("t.due_date = $due_date")
            params["due_date"] = due_date
        if priority is not None:
            sets.append("t.priority = $priority")
            params["priority"] = priority
        if not sets and project is None:
            return {"error": "No fields to update"}
        sets.append("t.updated_at = $now")
        q = f"""
        MATCH (t:Task) WHERE toLower(t.title) CONTAINS toLower($title)
        SET {', '.join(sets)}
        RETURN t.title, t.status, t.due_date, t.priority
        """
        rows = await self.query(q, params)
        if not rows:
            return {"error": f"No task found matching '{title}'"}
        result = {"title": rows[0][0], "status": rows[0][1],
                  "due_date": rows[0][2], "priority": rows[0][3]}
        # Auto-dismiss related reminders when task is done
        if status == "done" and rows:
            dismissed = await self._auto_dismiss_reminders(rows[0][0])
            if dismissed:
                result["dismissed_reminders"] = dismissed
        # Re-link to project if requested
        if project is not None:
            task_title = rows[0][0]
            await self.upsert_project(project)
            try:
                await self.create_relationship(
                    "Task", "title", task_title,
                    "BELONGS_TO", "Project", "name", project,
                )
                result["project"] = project
            except Exception as e:
                logger.debug("Task-Project link skipped: %s", e)
        return result

    async def merge_duplicate_tasks(self) -> dict:
        """Find and merge duplicate tasks. Keeps the one with highest priority / earliest due_date."""
        q_all = """
        MATCH (t:Task)
        WHERE t.status IN ['todo', 'in_progress']
        OPTIONAL MATCH (t)-[:BELONGS_TO]->(p:Project)
        RETURN ID(t) AS id, t.title, t.due_date, t.priority, t.status,
               t.energy_level, t.description, p.name
        ORDER BY t.title
        """
        rows = await self.query(q_all, {})
        if not rows:
            return {"merged_groups": [], "total_removed": 0}

        from collections import defaultdict
        groups: dict[str, list] = defaultdict(list)
        for row in rows:
            nid, title = row[0], row[1]
            key = title.strip().lower()
            groups[key].append({
                "id": nid, "title": title, "due_date": row[2],
                "priority": row[3], "status": row[4],
                "energy_level": row[5], "description": row[6],
                "project": row[7],
            })

        merged_groups = []
        total_removed = 0

        for key, items in groups.items():
            if len(items) < 2:
                continue
            # Keep: in_progress > todo, highest priority, earliest due_date, lowest ID
            def sort_key(item):
                status_rank = 0 if item["status"] == "in_progress" else 1
                prio = -(item["priority"] or 0)
                due = item["due_date"] or "9999"
                return (status_rank, prio, due, item["id"])
            items.sort(key=sort_key)
            keep = items[0]
            remove = items[1:]

            # Merge best properties into keeper
            best_priority = keep.get("priority") or 0
            best_description = keep.get("description")
            best_energy = keep.get("energy_level")
            best_project = keep.get("project")
            for item in remove:
                if (item.get("priority") or 0) > best_priority:
                    best_priority = item["priority"]
                if not best_description and item.get("description"):
                    best_description = item["description"]
                if not best_energy and item.get("energy_level"):
                    best_energy = item["energy_level"]
                if not best_project and item.get("project"):
                    best_project = item["project"]

            update_sets = ["t.updated_at = $now"]
            update_params: dict = {"kid": keep["id"], "now": _now()}
            if best_priority and best_priority != (keep.get("priority") or 0):
                update_sets.append("t.priority = $priority")
                update_params["priority"] = best_priority
            if best_description and best_description != keep.get("description"):
                update_sets.append("t.description = $description")
                update_params["description"] = best_description
            if best_energy and best_energy != keep.get("energy_level"):
                update_sets.append("t.energy_level = $energy_level")
                update_params["energy_level"] = best_energy

            q_update = f"""
            MATCH (t:Task) WHERE ID(t) = $kid
            SET {', '.join(update_sets)}
            """
            await self.query(q_update, update_params)

            # Link keeper to project if found
            if best_project and not keep.get("project"):
                try:
                    await self.create_relationship(
                        "Task", "title", keep["title"],
                        "BELONGS_TO", "Project", "name", best_project,
                    )
                except Exception:
                    pass

            # Delete duplicates
            remove_ids = [item["id"] for item in remove]
            q_delete = """
            MATCH (t:Task) WHERE ID(t) IN $ids
            DETACH DELETE t
            """
            await self.query(q_delete, {"ids": remove_ids})

            merged_groups.append({
                "kept": keep["title"],
                "kept_id": keep["id"],
                "removed_count": len(remove),
                "removed_ids": remove_ids,
            })
            total_removed += len(remove)

        return {"merged_groups": merged_groups, "total_removed": total_removed}

    # --- Sprint ---
    async def create_sprint(self, name: str, start_date: str | None = None,
                            end_date: str | None = None, **props) -> dict:
        """Create or update a Sprint node."""
        if not start_date:
            start_date = _now()[:10]
        if not end_date:
            d = datetime.fromisoformat(start_date) + timedelta(weeks=settings.sprint_default_weeks)
            end_date = d.strftime("%Y-%m-%d")
        extra = {k: v for k, v in props.items() if v is not None}
        sets = ""
        if extra:
            sets = ", " + ", ".join(f"s.{k} = ${k}" for k in extra)
        q = f"""
        MERGE (s:Sprint {{name: $name}})
        ON CREATE SET s.start_date = $start_date, s.end_date = $end_date,
                      s.status = 'planning', s.created_at = $now{sets}
        ON MATCH SET s.updated_at = $now{sets}
        RETURN s.name, s.status, s.start_date, s.end_date
        """
        rows = await self.query(q, {"name": name, "start_date": start_date,
                                    "end_date": end_date, "now": _now(), **extra})
        result = {"name": name, "status": "planning", "start_date": start_date, "end_date": end_date}
        if rows:
            result = {"name": rows[0][0], "status": rows[0][1],
                      "start_date": rows[0][2], "end_date": rows[0][3]}
        # Link to project if provided
        project = extra.get("project") or props.get("project")
        if project:
            await self.upsert_project(project)
            try:
                await self.create_relationship("Sprint", "name", name,
                                               "BELONGS_TO", "Project", "name", project)
            except Exception as e:
                logger.debug("Sprint-Project link skipped: %s", e)
            result["project"] = project
        return result

    async def update_sprint(self, name: str, **props) -> dict:
        """Update sprint properties."""
        filtered = {k: v for k, v in props.items() if v is not None}
        if not filtered:
            return {"error": "No properties to update"}
        filtered["updated_at"] = _now()
        sets = ", ".join(f"s.{k} = ${k}" for k in filtered)
        q = f"""
        MATCH (s:Sprint {{name: $name}})
        SET {sets}
        RETURN s.name, s.status, s.start_date, s.end_date, s.goal
        """
        rows = await self.query(q, {"name": name, **filtered})
        if not rows:
            return {"error": f"Sprint '{name}' not found"}
        return {"name": rows[0][0], "status": rows[0][1],
                "start_date": rows[0][2], "end_date": rows[0][3], "goal": rows[0][4]}

    async def assign_task_to_sprint(self, task_title: str, sprint_name: str) -> dict:
        """Link a Task to a Sprint via IN_SPRINT relationship."""
        q = """
        MATCH (t:Task {title: $task})
        MATCH (s:Sprint {name: $sprint})
        MERGE (t)-[:IN_SPRINT]->(s)
        RETURN t.title, s.name
        """
        rows = await self.query(q, {"task": task_title, "sprint": sprint_name})
        if not rows:
            return {"error": f"Task '{task_title}' or Sprint '{sprint_name}' not found"}
        return {"task": rows[0][0], "sprint": rows[0][1]}

    async def query_sprint(self, name: str) -> dict:
        """Sprint details + task breakdown."""
        q = """
        MATCH (s:Sprint {name: $name})
        OPTIONAL MATCH (t:Task)-[:IN_SPRINT]->(s)
        RETURN s.name, s.status, s.start_date, s.end_date, s.goal,
               count(t) as total,
               sum(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) as done,
               sum(CASE WHEN t.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress
        """
        rows = await self.query(q, {"name": name})
        if not rows:
            return {"error": f"Sprint '{name}' not found"}
        r = rows[0]
        total = r[5] or 0
        done = r[6] or 0
        return {
            "name": r[0], "status": r[1], "start_date": r[2], "end_date": r[3],
            "goal": r[4], "total_tasks": total, "done_tasks": done,
            "in_progress_tasks": r[7] or 0,
            "progress_pct": round(done / total * 100, 1) if total > 0 else 0,
        }

    async def query_sprints(self, status_filter: str | None = None) -> list[dict]:
        """List sprints optionally filtered by status."""
        where = "WHERE s.status = $status" if status_filter else ""
        q = f"""
        MATCH (s:Sprint)
        {where}
        OPTIONAL MATCH (t:Task)-[:IN_SPRINT]->(s)
        RETURN s.name, s.status, s.start_date, s.end_date, s.goal,
               count(t) as total,
               sum(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) as done
        ORDER BY s.start_date DESC
        LIMIT 20
        """
        params = {"status": status_filter} if status_filter else {}
        rows = await self.query(q, params)
        results = []
        for r in rows:
            total = r[5] or 0
            done = r[6] or 0
            results.append({
                "name": r[0], "status": r[1], "start_date": r[2], "end_date": r[3],
                "goal": r[4], "total_tasks": total, "done_tasks": done,
                "progress_pct": round(done / total * 100, 1) if total > 0 else 0,
            })
        return results

    async def query_sprint_burndown(self, name: str) -> dict:
        """Burndown data: ideal vs actual remaining."""
        sprint = await self.query_sprint(name)
        if "error" in sprint:
            return sprint
        total = sprint["total_tasks"]
        done = sprint["done_tasks"]
        remaining = total - done
        # Calculate days
        try:
            start = datetime.fromisoformat(sprint["start_date"])
            end = datetime.fromisoformat(sprint["end_date"])
            now = _now_dt()
            total_days = max((end - start).days, 1)
            days_passed = max((now - start).days, 0)
            days_left = max((end - now).days, 0)
        except (ValueError, TypeError):
            total_days, days_passed, days_left = 14, 0, 14
        # Ideal burndown: linear decrease
        ideal_remaining = total * (1 - days_passed / total_days) if total_days > 0 else total
        return {
            "name": sprint["name"], "status": sprint["status"],
            "total_tasks": total, "done_tasks": done, "remaining": remaining,
            "total_days": total_days, "days_passed": days_passed, "days_left": days_left,
            "ideal_remaining": round(ideal_remaining, 1),
            "progress_pct": sprint["progress_pct"],
        }

    async def complete_sprint(self, name: str) -> dict:
        """Mark sprint completed, calculate velocity."""
        sprint = await self.query_sprint(name)
        if "error" in sprint:
            return sprint
        total = sprint["total_tasks"]
        done = sprint["done_tasks"]
        # Calculate velocity (tasks per week)
        try:
            start = datetime.fromisoformat(sprint["start_date"])
            end = _now_dt()
            weeks = max((end - start).days / 7, 1)
            velocity = round(done / weeks, 1)
        except (ValueError, TypeError):
            velocity = 0
        q = """
        MATCH (s:Sprint {name: $name})
        SET s.status = 'completed', s.completed_at = $now, s.velocity = $velocity
        RETURN s.name, s.status
        """
        await self.query(q, {"name": name, "now": _now(), "velocity": velocity})
        return {
            "name": name, "status": "completed", "done_tasks": done,
            "total_tasks": total, "velocity": velocity,
        }

    async def query_sprint_velocity(self, project_name: str | None = None) -> dict:
        """Average velocity across completed sprints."""
        if project_name:
            q = """
            MATCH (s:Sprint)-[:BELONGS_TO]->(p:Project {name: $project})
            WHERE s.status = 'completed' AND s.velocity IS NOT NULL
            RETURN avg(s.velocity) as avg_vel, count(s) as cnt
            """
            rows = await self.query(q, {"project": project_name})
        else:
            q = """
            MATCH (s:Sprint)
            WHERE s.status = 'completed' AND s.velocity IS NOT NULL
            RETURN avg(s.velocity) as avg_vel, count(s) as cnt
            """
            rows = await self.query(q)
        if not rows or not rows[0][1]:
            return {"avg_velocity": 0, "completed_sprints": 0}
        return {"avg_velocity": round(rows[0][0], 1), "completed_sprints": rows[0][1]}

    # --- Focus Sessions ---
    async def start_focus_session(self, duration_minutes: int = 25,
                                  task_title: str | None = None,
                                  session_id: str | None = None) -> dict:
        """Create a FocusSession node, optionally link to a Task."""
        sid = session_id or _now().replace(":", "").replace("-", "")[:14]
        q = """
        CREATE (f:FocusSession {session_id: $sid, started_at: $now,
                                duration_minutes: $dur, completed: false})
        RETURN f.session_id, f.started_at
        """
        rows = await self.query(q, {"sid": sid, "now": _now(), "dur": duration_minutes})
        result = {"session_id": sid, "started_at": _now(), "duration_minutes": duration_minutes}
        if task_title:
            try:
                q_link = """
                MATCH (f:FocusSession {session_id: $sid})
                MATCH (t:Task)
                WHERE toLower(t.title) CONTAINS toLower($task)
                MERGE (f)-[:WORKED_ON]->(t)
                RETURN t.title
                """
                link_rows = await self.query(q_link, {"sid": sid, "task": task_title})
                if link_rows:
                    result["task"] = link_rows[0][0]
            except Exception as e:
                logger.debug("Focus-Task link skipped: %s", e)
        return result

    async def complete_focus_session(self, session_id: str | None = None,
                                     completed: bool = True) -> dict:
        """Complete the latest incomplete focus session."""
        if session_id:
            q = """
            MATCH (f:FocusSession {session_id: $sid})
            WHERE f.completed = false
            SET f.completed = $completed, f.ended_at = $now
            RETURN f.session_id, f.started_at, f.ended_at, f.duration_minutes
            """
            rows = await self.query(q, {"sid": session_id, "completed": completed, "now": _now()})
        else:
            q = """
            MATCH (f:FocusSession)
            WHERE f.completed = false
            WITH f ORDER BY f.started_at DESC LIMIT 1
            SET f.completed = $completed, f.ended_at = $now
            RETURN f.session_id, f.started_at, f.ended_at, f.duration_minutes
            """
            rows = await self.query(q, {"completed": completed, "now": _now()})
        if not rows:
            return {"error": "No active focus session found"}
        return {
            "session_id": rows[0][0], "started_at": rows[0][1],
            "ended_at": rows[0][2], "duration_minutes": rows[0][3],
            "completed": completed,
        }

    async def query_focus_stats(self) -> dict:
        """Focus session statistics: today/week/total + by task."""
        today = _now()[:10]
        week_ago = (_now_dt() - timedelta(days=7)).strftime("%Y-%m-%d")

        # Today
        q_today = """
        MATCH (f:FocusSession)
        WHERE f.completed = true AND f.started_at >= $today
        RETURN count(f), sum(f.duration_minutes)
        """
        r1 = await self.query(q_today, {"today": today})
        today_sessions = r1[0][0] if r1 else 0
        today_minutes = int(r1[0][1] or 0) if r1 else 0

        # Week
        q_week = """
        MATCH (f:FocusSession)
        WHERE f.completed = true AND f.started_at >= $week_ago
        RETURN count(f), sum(f.duration_minutes)
        """
        r2 = await self.query(q_week, {"week_ago": week_ago})
        week_sessions = r2[0][0] if r2 else 0
        week_minutes = int(r2[0][1] or 0) if r2 else 0

        # Total
        q_total = """
        MATCH (f:FocusSession)
        WHERE f.completed = true
        RETURN count(f), sum(f.duration_minutes)
        """
        r3 = await self.query(q_total)
        total_sessions = r3[0][0] if r3 else 0
        total_minutes = int(r3[0][1] or 0) if r3 else 0

        # By task
        q_by_task = """
        MATCH (f:FocusSession)-[:WORKED_ON]->(t:Task)
        WHERE f.completed = true
        RETURN t.title, count(f), sum(f.duration_minutes)
        ORDER BY sum(f.duration_minutes) DESC
        LIMIT 10
        """
        r4 = await self.query(q_by_task)
        by_task = [{"task": r[0], "sessions": r[1], "minutes": int(r[2] or 0)} for r in (r4 or [])]

        return {
            "today_sessions": today_sessions, "today_minutes": today_minutes,
            "week_sessions": week_sessions, "week_minutes": week_minutes,
            "total_sessions": total_sessions, "total_minutes": total_minutes,
            "by_task": by_task,
        }

    # --- Energy-Aware Time-Blocking ---
    async def suggest_time_blocks(self, date_str: str,
                                  energy_profile: str | None = None) -> dict:
        """Generate time-block suggestions based on energy profile and task priorities."""
        profile = energy_profile or settings.default_energy_profile

        # Parse energy hours from config
        def parse_range(s: str) -> tuple[int, int]:
            parts = s.split("-")
            return int(parts[0]), int(parts[1])

        peak_start, peak_end = parse_range(settings.energy_peak_hours)
        low_start, low_end = parse_range(settings.energy_low_hours)

        # Adjust based on profile
        if profile == "tired":
            peak_start += 1
            peak_end -= 1
            low_start -= 1
            low_end += 1
        elif profile == "energized":
            peak_start -= 1
            peak_end += 1

        # Clamp to work day
        day_start = settings.work_day_start
        day_end = settings.work_day_end
        peak_start = max(peak_start, day_start)
        peak_end = min(peak_end, day_end)
        low_start = max(low_start, day_start)
        low_end = min(low_end, day_end)

        # Fetch tasks (todo/in_progress, due today or no due_date, not yet scheduled)
        eod = date_str + "T23:59:59"
        q = """
        MATCH (t:Task)
        WHERE t.status IN ['todo', 'in_progress']
          AND (t.start_time IS NULL OR t.start_time = '')
          AND (t.due_date IS NULL OR t.due_date <= $eod)
        RETURN t.title, t.priority, t.energy_level, t.estimated_duration
        ORDER BY t.priority DESC
        LIMIT 20
        """
        rows = await self.query(q, {"eod": eod})
        if not rows:
            return {"blocks": [], "energy_profile": profile, "date": date_str}

        # Bucket tasks by energy
        high_tasks, medium_tasks, low_tasks = [], [], []
        for r in rows:
            task = {
                "title": r[0], "priority": r[1] or 0,
                "energy_level": r[2] or "medium",
                "duration": r[3] or settings.time_block_slot_minutes,
            }
            el = (task["energy_level"] or "medium").lower()
            if el == "high":
                high_tasks.append(task)
            elif el == "low":
                low_tasks.append(task)
            else:
                medium_tasks.append(task)

        blocks = []
        slot = settings.time_block_slot_minutes

        def schedule_tasks(tasks: list[dict], start_h: int, end_h: int) -> None:
            current_min = start_h * 60
            end_min = end_h * 60
            for task in tasks:
                dur = min(task["duration"], 120)  # cap at 2 hours
                if current_min + dur > end_min:
                    break
                s_h, s_m = divmod(current_min, 60)
                e_min = current_min + dur
                e_h, e_m_ = divmod(e_min, 60)
                blocks.append({
                    "task_title": task["title"],
                    "start_time": f"{date_str}T{s_h:02d}:{s_m:02d}:00",
                    "end_time": f"{date_str}T{e_h:02d}:{e_m_:02d}:00",
                    "energy_level": task["energy_level"],
                    "priority": task["priority"],
                })
                current_min = e_min

        # Schedule: peak → high, low hours → low, remaining → medium
        schedule_tasks(high_tasks, peak_start, peak_end)
        schedule_tasks(low_tasks, low_start, low_end)
        # Medium: fill remaining work hours
        medium_start = peak_end if peak_end < low_start else low_end
        medium_end = low_start if peak_end < low_start else day_end
        schedule_tasks(medium_tasks, medium_start, medium_end)

        return {"blocks": blocks, "energy_profile": profile, "date": date_str}

    async def apply_time_blocks(self, blocks: list[dict], date_str: str) -> dict:
        """Apply time-block suggestions to Task nodes (SET start_time/end_time)."""
        applied = 0
        for block in blocks:
            title = block.get("task_title", "")
            start = block.get("start_time", "")
            end = block.get("end_time", "")
            if not title or not start or not end:
                continue
            q = """
            MATCH (t:Task {title: $title})
            SET t.start_time = $start, t.end_time = $end, t.updated_at = $now
            RETURN t.title
            """
            rows = await self.query(q, {"title": title, "start": start, "end": end, "now": _now()})
            if rows:
                applied += 1
        return {"applied": applied, "date": date_str}

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
        name = await self.resolve_entity_name(name, "Company")
        props_str = self._build_set_clause(props, var="c")
        q = f"""
        MERGE (c:Company {{name: $name}})
        ON CREATE SET c.created_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Topic ---
    async def upsert_topic(self, name: str, **props) -> None:
        name = await self.resolve_entity_name(name, "Topic")
        props_str = self._build_set_clause(props, var="t")
        q = f"""
        MERGE (t:Topic {{name: $name}})
        ON CREATE SET t.created_at = $now {props_str}
        """
        await self._graph.query(q, params={"name": name, "now": _now(), **props})

    # --- Tag ---
    _TAG_ALIASES: dict[str, str] = {
        "programming": "برمجة", "coding": "برمجة", "code": "برمجة",
        "finance": "مالية", "money": "مالية",
        "health": "صحة", "medical": "صحة",
        "work": "عمل", "job": "عمل",
        "home": "منزل", "house": "منزل",
        "food": "طعام", "cooking": "طبخ",
        "travel": "سفر",
        "education": "تعليم", "learning": "تعليم",
        "shopping": "تسوق",
        "car": "سيارة", "auto": "سيارة",
        "tech": "تقنية", "technology": "تقنية",
    }

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        if not tag:
            return ""
        t = tag.strip().lower()
        return GraphService._TAG_ALIASES.get(t, t)

    async def upsert_tag(self, name: str) -> str:
        """Normalize, resolve, and create/merge a tag. Returns canonical name."""
        name = self._normalize_tag(name)
        if not name:
            return ""
        # Vector-based dedup
        if self._vector_service and settings.entity_resolution_enabled:
            try:
                results = await self._vector_service.search(name, limit=3, entity_type="Tag")
                for r in results:
                    other = r["metadata"].get("entity_name", "")
                    if other and other.lower() != name.lower() and r["score"] >= 0.85:
                        logger.info("Tag resolved: '%s' -> '%s' (%.2f)", name, other, r["score"])
                        name = other
                        break
                else:
                    await self._vector_service.upsert_chunks(
                        [name],
                        [{"source_type": "entity", "entity_type": "Tag", "entity_name": name}],
                    )
            except Exception as e:
                logger.debug("Tag resolution failed: %s", e)
        q = "MERGE (t:Tag {name: $name}) ON CREATE SET t.created_at = $now"
        await self._graph.query(q, params={"name": name, "now": _now()})
        return name

    async def tag_entity(self, entity_label: str, entity_key: str, entity_value: str, tag_name: str) -> None:
        """Create TAGGED_WITH relationship between an entity and a tag."""
        tag_name = await self.upsert_tag(tag_name)
        if not tag_name:
            return
        try:
            await self.create_relationship(
                entity_label, entity_key, entity_value,
                "TAGGED_WITH",
                "Tag", "name", tag_name,
            )
        except Exception as e:
            logger.debug("Tag link skipped: %s", e)

    # --- File ---
    async def ensure_file_stub(self, file_hash: str, filename: str) -> None:
        """Create minimal File node so EXTRACTED_FROM links can target it during ingestion."""
        q = """
        MERGE (f:File {file_hash: $fhash})
        ON CREATE SET f.filename = $fn, f.created_at = $now
        """
        await self._graph.query(q, params={"fhash": file_hash, "fn": filename, "now": _now()})

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

    async def find_file_by_filename(self, filename: str) -> dict | None:
        """Find the most recent File node with this filename."""
        q = """
        MATCH (f:File)
        WHERE f.filename = $filename
        RETURN f
        ORDER BY f.updated_at DESC, f.created_at DESC
        LIMIT 1
        """
        rows = await self.query(q, {"filename": filename})
        if rows and rows[0]:
            node = rows[0][0]
            props = node.properties if hasattr(node, "properties") else {}
            return {"file_hash": props.get("file_hash"), "properties": props}
        return None

    async def supersede_file(self, new_hash: str, old_hash: str) -> None:
        """Mark old file as superseded by new file."""
        q = """
        MATCH (old:File {file_hash: $old_hash})
        MATCH (new:File {file_hash: $new_hash})
        SET old.superseded_by = $new_hash, old.updated_at = $now
        MERGE (new)-[:SUPERSEDES]->(old)
        """
        await self._graph.query(
            q, params={"old_hash": old_hash, "new_hash": new_hash, "now": _now()}
        )

    async def cleanup_file_entities(self, old_file_hash: str) -> int:
        """Delete entities that were ONLY extracted from the old file (no other source)."""
        q = """
        MATCH (e)-[:EXTRACTED_FROM]->(old:File {file_hash: $old_hash})
        OPTIONAL MATCH (e)-[:EXTRACTED_FROM]->(other:File)
        WHERE other.file_hash <> $old_hash
        WITH e, old, other
        WHERE other IS NULL
        DETACH DELETE e
        RETURN count(e) as deleted
        """
        result = await self._graph.query(q, params={"old_hash": old_file_hash})
        deleted = result.result_set[0][0] if result.result_set else 0
        if deleted > 0:
            logger.info("Cleaned up %d orphaned entities from file %s…", deleted, old_file_hash[:12])
        return deleted

    async def _unlink_file_entities(self, file_hash: str) -> None:
        """Remove all EXTRACTED_FROM edges pointing to a file."""
        q = """
        MATCH (e)-[r:EXTRACTED_FROM]->(f:File {file_hash: $fhash})
        DELETE r
        """
        await self._graph.query(q, params={"fhash": file_hash})

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

    # --- Entity-to-File linking ---
    _PSEUDO_ENTITY_TYPES = {"DebtPayment", "ItemUsage", "ItemMove", "ReminderAction"}
    _TOOL_ONLY_TYPES = {"Section", "ListEntry"}  # Created via tools, not extraction
    _PROJECT_LINKABLE_TYPES = {"Task", "Knowledge", "Idea", "Sprint", "Section", "List"}
    _SECTION_LINKABLE_TYPES = {"Task", "Knowledge", "Idea", "Reminder", "Item", "Sprint", "List"}
    _DEFAULT_PHASES = ["Planning", "Preparation", "Execution", "Review"]

    async def _link_entity_to_file(self, entity_type: str, entity_name: str, file_hash: str) -> None:
        """Create EXTRACTED_FROM relationship between entity and File node."""
        key_field = "name" if entity_type not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
        q = f"""
        MATCH (e:{entity_type} {{{key_field}: $ename}})
        MATCH (f:File {{file_hash: $fhash}})
        MERGE (e)-[:EXTRACTED_FROM]->(f)
        """
        await self._graph.query(q, params={"ename": entity_name, "fhash": file_hash})

    # --- Upsert from LLM-extracted facts ---
    async def upsert_from_facts(self, facts: dict, file_hash: str | None = None, project_name: str | None = None) -> int:
        # Pre-resolve all entity names in batch (one embed + parallel searches)
        names_to_resolve: set[tuple[str, str]] = set()
        for entity in facts.get("entities", []):
            etype = entity.get("entity_type", "")
            ename = entity.get("entity_name", "")
            if etype and ename:
                names_to_resolve.add((ename, etype))
                for rel in entity.get("relationships", []):
                    tt = rel.get("target_type", "")
                    tn = rel.get("target_name", "")
                    if tt and tn:
                        names_to_resolve.add((tn, tt))
        if names_to_resolve:
            await self.resolve_entity_names_batch(list(names_to_resolve))

        count = 0
        try:
            for entity in facts.get("entities", []):
                etype = entity.get("entity_type", "")
                ename = entity.get("entity_name", "")
                props = entity.get("properties", {})
                rels = entity.get("relationships", [])

                if not etype or not ename:
                    continue

                # Suppress rogue Project creation when active project is set
                if etype == "Project" and project_name:
                    logger.info("Suppressed Project entity '%s' — active project is '%s'", ename, project_name)
                    continue

                # Skip tool-only types (Section, ListEntry) — created via tools, not extraction
                if etype in self._TOOL_ONLY_TYPES:
                    continue

                try:
                    # Sprint handling
                    if etype == "Sprint":
                        start_date = props.pop("start_date", None)
                        end_date = props.pop("end_date", None)
                        await self.create_sprint(ename, start_date, end_date, **props)
                        count += 1
                        # Link to source file
                        if file_hash:
                            try:
                                await self._link_entity_to_file(etype, ename, file_hash)
                            except Exception as e:
                                logger.debug("EXTRACTED_FROM link skipped for %s/%s: %s", etype, ename, e)
                        # Create relationships for Sprint
                        for rel in rels:
                            target_type = rel.get("target_type", "")
                            target_name = rel.get("target_name", "")
                            rel_type = rel.get("type", "RELATED_TO")
                            if target_type and target_name:
                                if target_type in ("Person", "Company", "Project", "Topic"):
                                    target_name = await self.resolve_entity_name(target_name, target_type)
                                target_key = "name" if target_type not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
                                try:
                                    await self.create_relationship(
                                        "Sprint", "name", ename, rel_type, target_type, target_key, target_name
                                    )
                                except Exception as e:
                                    logger.debug("Sprint relationship skipped: %s", e)
                        continue

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
                        "List": lambda n, **p: self.create_list(n, **p),
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
                                entity["_failed"] = True
                        else:
                            entity["_failed"] = True
                        continue  # Skip relationship creation for pseudo-entity

                    if etype == "ItemUsage":
                        qty_used = props.get("quantity_used", 1)
                        result = await self.adjust_item_quantity(ename, -abs(int(qty_used)))
                        if "error" not in result:
                            count += 1
                        else:
                            logger.warning("ItemUsage failed: %s", result["error"])
                            entity["_failed"] = True
                        continue  # Skip relationship creation for pseudo-entity

                    if etype == "ItemMove":
                        to_loc = props.get("to_location", "")
                        from_loc = props.get("from_location")
                        if to_loc:
                            result = await self.move_item(ename, to_loc, from_loc)
                            if "error" not in result:
                                count += 1
                            else:
                                logger.warning("ItemMove failed: %s", result["error"])
                                entity["_failed"] = True
                        else:
                            entity["_failed"] = True
                        continue  # Skip relationship creation for pseudo-entity

                    if etype == "ReminderAction":
                        action = props.get("action", "done")
                        reminder_title = props.get("reminder_title", ename)
                        snooze_until = props.get("snooze_until")
                        result = await self.update_reminder_status(reminder_title, action, snooze_until)
                        if "error" not in result:
                            count += 1
                            logger.info("ReminderAction: %s → %s", reminder_title, action)
                        else:
                            logger.warning("ReminderAction failed: %s", result["error"])
                            entity["_failed"] = True
                        continue

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

                    # Link entity to source file
                    if file_hash and etype not in self._PSEUDO_ENTITY_TYPES:
                        try:
                            await self._link_entity_to_file(etype, ename, file_hash)
                        except Exception as e:
                            logger.debug("EXTRACTED_FROM link skipped for %s/%s: %s", etype, ename, e)

                    # Auto-link to active project if entity type is linkable
                    if project_name and etype in self._PROJECT_LINKABLE_TYPES:
                        has_project_rel = any(
                            r.get("target_type") == "Project" for r in rels
                        )
                        if not has_project_rel:
                            key_field = "name" if etype not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
                            try:
                                await self.create_relationship(
                                    etype, key_field, ename,
                                    "BELONGS_TO", "Project", "name", project_name,
                                )
                                logger.info("Auto-linked %s '%s' to active project '%s'", etype, ename, project_name)
                            except Exception as e:
                                logger.debug("Active project link skipped for %s/%s: %s", etype, ename, e)

                    # Auto-tag Knowledge by category
                    if etype == "Knowledge":
                        cat = props.get("category") or self._guess_knowledge_category(ename, props.get("content", ""))
                        if cat:
                            await self.tag_entity("Knowledge", "title", ename, cat)

                    # Auto-link Task to Project: if no BELONGS_TO in rels, search project names
                    if etype == "Task":
                        has_project_rel = any(
                            r.get("target_type") == "Project" or r.get("type") == "BELONGS_TO"
                            for r in rels
                        )
                        if not has_project_rel:
                            try:
                                q_projects = "MATCH (p:Project) RETURN p.name"
                                proj_rows = await self.query(q_projects)
                                task_lower = ename.lower()
                                for pr in (proj_rows or []):
                                    pname = pr[0]
                                    if pname and pname.lower() in task_lower:
                                        await self.create_relationship(
                                            "Task", "title", ename,
                                            "BELONGS_TO", "Project", "name", pname,
                                        )
                                        logger.info("Auto-linked task '%s' to project '%s'", ename, pname)
                                        break
                            except Exception as e:
                                logger.debug("Auto-link task to project skipped: %s", e)

                    # Create relationships
                    for rel in rels:
                        target_type = rel.get("target_type", "")
                        target_name = rel.get("target_name", "")
                        rel_type = rel.get("type", "RELATED_TO")
                        if target_type and target_name and etype not in ("Debt",):
                            # Resolve target name for entity resolution
                            if target_type in ("Person", "Company", "Project", "Topic"):
                                target_name = await self.resolve_entity_name(target_name, target_type)
                            # Handle Tag targets via TAGGED_WITH
                            if target_type == "Tag":
                                key_field = "name" if etype not in ("Task", "Idea", "Reminder", "Knowledge") else "title"
                                await self.tag_entity(etype, key_field, ename, target_name)
                                continue
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
        finally:
            self._resolution_cache.clear()
        return count

    # --- GraphRAG queries ---
    async def query_entity_context(self, label: str, key_field: str, value: str) -> str:
        """Multi-hop context with configurable depth."""
        max_hops = settings.graph_max_hops
        if max_hops <= 2:
            q = f"""
            MATCH (root:{label} {{{key_field}: $value}})
            OPTIONAL MATCH (root)-[r1]-(n1)
            OPTIONAL MATCH (n1)-[r2]-(n2)
            WHERE n2 <> root
            RETURN root, type(r1), labels(n1)[0], n1,
                   type(r2), labels(n2)[0], n2
            LIMIT 50
            """
            rows = await self.query(q, {"value": value})
            return self._format_graph_context(rows)

        # 3-hop: unrestricted hop 1-2, selective hop 3
        q = f"""
        MATCH (root:{label} {{{key_field}: $value}})
        OPTIONAL MATCH (root)-[r1]-(n1)
        OPTIONAL MATCH (n1)-[r2]-(n2)
        WHERE n2 <> root
        OPTIONAL MATCH (n2)-[r3]-(n3)
        WHERE n3 <> root AND n3 <> n1
          AND type(r3) IN ['BELONGS_TO','INVOLVES','WORKS_AT','RELATED_TO','TAGGED_WITH','STORED_IN','SIMILAR_TO']
        RETURN root, type(r1), labels(n1)[0], n1,
               type(r2), labels(n2)[0], n2,
               type(r3), labels(n3)[0], n3
        LIMIT 80
        """
        rows = await self.query(q, {"value": value})
        return self._format_graph_context_3hop(rows)

    async def query_person_context(self, query: str) -> str:
        """Find person by exact name or fuzzy match from query text."""
        # 1. Try exact match
        ctx = await self.query_entity_context("Person", "name", query)
        if ctx:
            return ctx

        # 2. Extract candidate names: capitalized words (English proper nouns)
        stop_words = {
            "how", "old", "is", "my", "the", "what", "who", "when", "where",
            "about", "tell", "me", "many", "much", "does", "do", "are", "was",
            "number", "name", "age", "born", "date", "family", "all", "list",
        }
        candidates = []
        for w in query.split():
            # Strip possessive 's
            clean = w.rstrip("'s") if w.endswith("'s") or w.endswith("s") else w
            if not clean:
                continue
            if len(clean) > 2 and clean[0].isupper() and clean.isalpha() and clean.lower() not in stop_words:
                candidates.append(clean)
        # Also add Arabic tokens (non-ASCII words)
        candidates += [w for w in query.split() if any(ord(c) > 127 for c in w) and len(w) > 1]

        all_parts = []
        seen_names = set()
        for candidate in candidates:
            rows = await self.query(
                "MATCH (p:Person) WHERE toLower(p.name) CONTAINS toLower($w) RETURN p.name LIMIT 5",
                {"w": candidate},
            )
            for row in (rows or []):
                name = row[0]
                if name in seen_names:
                    continue
                seen_names.add(name)
                ctx = await self.query_entity_context("Person", "name", name)
                if ctx:
                    all_parts.append(ctx)
        if all_parts:
            return "\n\n".join(all_parts)

        # 3. No specific name found — return summary of all persons with relationships
        rows = await self.query(
            """MATCH (p:Person)
            OPTIONAL MATCH (p)-[r]->(other:Person)
            RETURN p, collect(DISTINCT {rel: type(r), target: other.name}) as rels
            ORDER BY p.name LIMIT 20"""
        )
        if not rows:
            return ""
        parts = ["Known persons:"]
        for row in rows:
            props = self._clean_props(row[0].properties)
            name = props.pop("name", "?")
            name_ar = props.pop("name_ar", "")
            display = f"{name_ar} ({name})" if name_ar else name
            details = []
            for k, v in props.items():
                if v:
                    details.append(f"{k}: {v}")
            rels = row[1] if len(row) > 1 else []
            rel_strs = [f"{r['rel']} → {r['target']}" for r in rels if r.get("target")]
            line = f"  - {display}"
            if details:
                line += f" ({', '.join(details)})"
            if rel_strs:
                line += f" [{', '.join(rel_strs)}]"
            parts.append(line)
        return "\n".join(parts)

    async def query_project_context(self, name: str) -> str:
        return await self.query_entity_context("Project", "name", name)

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

    @staticmethod
    def _guess_knowledge_category(title: str, content: str = "") -> str:
        """Keyword heuristic for knowledge category."""
        combined = f"{title} {content}".lower()
        rules = [
            (["python", "code", "api", "bug", "git", "docker", "server", "database", "sql", "linux"], "تقنية"),
            (["recipe", "cook", "food", "طبخ", "أكل", "وصفة"], "طبخ"),
            (["health", "medicine", "doctor", "صحة", "دواء", "علاج"], "صحة"),
            (["car", "engine", "سيارة", "محرك", "صيانة", "oil change"], "سيارة"),
            (["money", "invest", "stock", "bank", "فلوس", "استثمار", "بنك"], "مالية"),
            (["islam", "quran", "hadith", "prayer", "قرآن", "حديث", "صلاة", "دعاء"], "دين"),
            (["travel", "flight", "hotel", "visa", "سفر", "فندق", "تأشيرة"], "سفر"),
            (["work", "meeting", "شغل", "وظيفة", "اجتماع"], "عمل"),
            (["home", "plumbing", "electric", "بيت", "سباكة", "كهرباء"], "منزل"),
        ]
        for keywords, category in rules:
            if any(kw in combined for kw in keywords):
                return category
        return "عام"

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
    async def query_project_details(self, name: str) -> str:
        """Return all properties, sections, lists, and linked tasks for a single project."""
        name = await self.resolve_entity_name(name, "Project")
        q = """
        MATCH (p:Project)
        WHERE toLower(p.name) CONTAINS toLower($name)
        OPTIONAL MATCH (t:Task)-[:BELONGS_TO]->(p)
        WHERE NOT (t)-[:IN_SECTION]->(:Section)
        OPTIONAL MATCH (p)-[:HAS_SECTION]->(s:Section)
        RETURN p,
               collect(DISTINCT {title: t.title, status: t.status, priority: t.priority}),
               collect(DISTINCT {sname: s.name, stype: s.section_type, sorder: s.order, sstatus: s.status})
        """
        rows = await self.query(q, {"name": name})
        if not rows:
            return f"No project found matching '{name}'."

        node_props = rows[0][0].properties if hasattr(rows[0][0], "properties") else rows[0][0]
        unsectioned_tasks = [t for t in (rows[0][1] or []) if t.get("title")]
        sections_raw = [s for s in (rows[0][2] or []) if s.get("sname")]

        parts = [f"Project: {node_props.get('name', name)}"]
        skip_keys = {"name", "created_at", "updated_at", "name_aliases"}
        aliases = node_props.get("name_aliases")
        if aliases:
            parts.append(f"  aliases: {', '.join(aliases)}")
        for k, v in node_props.items():
            if k in skip_keys or v is None:
                continue
            parts.append(f"  {k}: {v}")

        # Show sections with their entities
        seen_sections = set()
        sorted_sections = sorted(sections_raw, key=lambda s: (s.get("sorder") or 999, s.get("sname", "")))
        for sec in sorted_sections:
            sname = sec["sname"]
            if sname in seen_sections:
                continue
            seen_sections.add(sname)
            stype = sec.get("stype", "topic")
            label = " (phase)" if stype == "phase" else ""
            active = " *active*" if node_props.get("active_phase") == sname else ""
            parts.append(f"\n  Section: {sname}{label}{active}")

            # Query entities in this section
            q_sec = """
            MATCH (s:Section {name: $sname})<-[:IN_SECTION]-(e)
            MATCH (:Project {name: $pname})-[:HAS_SECTION]->(s)
            RETURN labels(e)[0], e.name, e.title, e.status
            LIMIT 50
            """
            sec_rows = await self.query(q_sec, {"sname": sname, "pname": node_props.get("name", name)})
            if sec_rows:
                for sr in sec_rows:
                    elabel = sr[0]
                    ename = sr[1] or sr[2] or "?"
                    estatus = f" [{sr[3]}]" if sr[3] else ""
                    parts.append(f"    - [{elabel}] {ename}{estatus}")
            else:
                parts.append("    (empty)")

        # Unsectioned tasks
        if unsectioned_tasks:
            parts.append(f"\n  Tasks (unsectioned, {len(unsectioned_tasks)}):")
            for t in unsectioned_tasks:
                status_tag = f" [{t['status']}]" if t.get("status") else ""
                parts.append(f"    - {t['title']}{status_tag}")

        # Lists linked to project
        q_lists = """
        MATCH (l:List)-[:BELONGS_TO]->(p:Project {name: $pname})
        OPTIONAL MATCH (l)-[:HAS_ENTRY]->(e:ListEntry)
        RETURN l.name, l.list_type, count(e), sum(CASE WHEN e.checked = true THEN 1 ELSE 0 END)
        """
        list_rows = await self.query(q_lists, {"pname": node_props.get("name", name)})
        if list_rows and any(r[0] for r in list_rows):
            parts.append("\n  Lists:")
            for r in list_rows:
                if r[0]:
                    total = r[2] or 0
                    checked = r[3] or 0
                    progress = f" ({checked}/{total})" if total > 0 else ""
                    parts.append(f"    - {r[0]} [{r[1]}]{progress}")

        return "\n".join(parts)

    async def query_projects_overview(self, status_filter: str | None = None) -> str:
        """Projects with their linked tasks, progress %, and ETA."""
        filter_clause = "WHERE toLower(p.status) = toLower($status)" if status_filter else ""
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

        # Velocity: tasks done in last 3 weeks / 3
        three_weeks_ago = (_now_dt() - timedelta(weeks=3)).isoformat()

        parts = ["Projects:"]
        for r in rows:
            name, status, desc, priority, total, done = r
            total = total or 0
            done = done or 0
            progress_pct = round(done / total * 100, 1) if total > 0 else 0
            progress = f" ({progress_pct}% complete, {done}/{total} tasks)" if total > 0 else ""
            priority_tag = f" [priority:{priority}]" if priority else ""
            status_tag = f" [{status}]" if status else ""

            # ETA for active projects
            eta_tag = ""
            if total > 0 and done < total and status in ("active", "in_progress", None):
                q_vel = """
                MATCH (t:Task)-[:BELONGS_TO]->(p:Project {name: $pname})
                WHERE t.status = 'done' AND t.updated_at >= $since
                RETURN count(t)
                """
                vel_rows = await self.query(q_vel, {"pname": name, "since": three_weeks_ago})
                done_recent = vel_rows[0][0] if vel_rows and vel_rows[0][0] else 0
                if done_recent > 0:
                    tasks_per_week = done_recent / 3
                    remaining = total - done
                    weeks_left = remaining / tasks_per_week
                    eta_date = (_now_dt() + timedelta(weeks=weeks_left)).strftime("%Y-%m-%d")
                    eta_tag = f" [ETA: ~{eta_date}]"

            parts.append(f"  - {name}{status_tag}{priority_tag}{progress}{eta_tag}")
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
        RETURN t.title, t.status, t.due_date, t.priority, p.name,
               t.estimated_duration, t.energy_level, t.start_time, t.end_time
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
            title, status, due_date, priority, project = r[0], r[1], r[2], r[3], r[4]
            est_dur, energy, start_t, end_t = r[5], r[6], r[7], r[8]
            status_tag = f" [{status}]"
            due = f" (due: {due_date})" if due_date else ""
            proj = f" @ {project}" if project else ""
            prio = f" [priority:{priority}]" if priority else ""
            dur = f" ~{est_dur}min" if est_dur else ""
            eng = f" energy:{energy}" if energy else ""
            sched = ""
            if start_t and end_t:
                sched = f" [{start_t[-5:]}-{end_t[-5:]}]"
            parts.append(f"  - {title}{status_tag}{prio}{dur}{eng}{due}{sched}{proj}")
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
    async def upsert_item(self, name: str, quantity_mode: str = "set", **props) -> dict:
        """Create or update an inventory Item node. If location provided, link to Location node.

        quantity_mode: "set" (default) replaces quantity on match, "add" increments it.
        """
        name = await self.resolve_entity_name(name, "Item")
        location = props.pop("location", None)
        if location:
            location = self._normalize_location(location)
        category = props.get("category")
        if category:
            props["category"] = self._normalize_category(category)
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

        qty_expr = "i.quantity + $quantity" if quantity_mode == "add" else "$quantity"
        q = f"""
        MERGE (i:Item {{name: $name}})
        ON CREATE SET i.created_at = $now, i.quantity = $quantity, i.status = 'active'{on_create_extra}
        ON MATCH SET i.updated_at = $now, i.quantity = {qty_expr}{on_match_extra}
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
        else:
            # Return existing location if item already has one
            q_existing_loc = """
            MATCH (i:Item {name: $name})-[:STORED_IN]->(l:Location)
            RETURN l.path LIMIT 1
            """
            loc_rows = await self.query(q_existing_loc, {"name": name})
            if loc_rows and loc_rows[0][0]:
                result["location"] = loc_rows[0][0]

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

    async def query_inventory_report(self) -> dict:
        """Comprehensive inventory report with 7 sub-queries."""
        top_n = settings.inventory_report_top_n

        # 1. Totals
        q1 = "MATCH (i:Item) WHERE i.status = 'active' RETURN count(i), sum(i.quantity)"
        r1 = await self.query(q1)
        total_items = r1[0][0] if r1 else 0
        total_qty = r1[0][1] if r1 else 0

        # 2. By category
        q2 = """
        MATCH (i:Item) WHERE i.status = 'active' AND i.category IS NOT NULL
        RETURN i.category, count(i), sum(i.quantity)
        ORDER BY count(i) DESC
        """
        r2 = await self.query(q2)
        by_category = [{"category": r[0], "items": r[1], "quantity": r[2]} for r in r2]

        # 3. By location
        q3 = """
        MATCH (i:Item)-[:STORED_IN]->(l:Location)
        WHERE i.status = 'active'
        RETURN l.path, count(i), sum(i.quantity)
        ORDER BY count(i) DESC
        """
        r3 = await self.query(q3)
        by_location = [{"location": r[0], "items": r[1], "quantity": r[2]} for r in r3]

        # 4. By condition
        q4 = """
        MATCH (i:Item) WHERE i.status = 'active' AND i.condition IS NOT NULL
        RETURN i.condition, count(i)
        ORDER BY count(i) DESC
        """
        r4 = await self.query(q4)
        by_condition = [{"condition": r[0], "count": r[1]} for r in r4]

        # 5. Without location
        q5 = """
        MATCH (i:Item)
        WHERE i.status = 'active' AND NOT (i)-[:STORED_IN]->()
        RETURN count(i)
        """
        r5 = await self.query(q5)
        no_location = r5[0][0] if r5 else 0

        # 6. Unused (no last_used_at or old)
        cutoff = (_now_dt() - timedelta(days=settings.inventory_unused_days)).isoformat()
        q6 = """
        MATCH (i:Item)
        WHERE i.status = 'active'
          AND (i.last_used_at IS NULL OR i.last_used_at < $cutoff)
        RETURN count(i)
        """
        r6 = await self.query(q6, {"cutoff": cutoff})
        unused_count = r6[0][0] if r6 else 0

        # 7. Most items by quantity
        q7 = f"""
        MATCH (i:Item) WHERE i.status = 'active'
        RETURN i.name, i.quantity, i.category
        ORDER BY i.quantity DESC
        LIMIT {top_n}
        """
        r7 = await self.query(q7)
        top_by_quantity = [{"name": r[0], "quantity": r[1], "category": r[2]} for r in r7]

        return {
            "total_items": total_items,
            "total_quantity": total_qty,
            "by_category": by_category,
            "by_location": by_location,
            "by_condition": by_condition,
            "without_location": no_location,
            "unused_count": unused_count,
            "top_by_quantity": top_by_quantity,
        }

    async def update_item(self, name: str, **props) -> dict:
        """Update an existing Item. Handles location changes by re-linking."""
        location = props.pop("location", None)
        if location:
            location = self._normalize_location(location)
        if "category" in props and props["category"]:
            props["category"] = self._normalize_category(props["category"])

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

    async def find_item_by_barcode(self, barcode: str) -> dict | None:
        """Find item by barcode value."""
        q = """
        MATCH (i:Item)
        WHERE i.barcode = $barcode AND i.status = 'active'
        OPTIONAL MATCH (i)-[:STORED_IN]->(l:Location)
        RETURN i.name, i.quantity, i.category, i.barcode_type, l.path
        LIMIT 1
        """
        rows = await self.query(q, {"barcode": barcode})
        if not rows:
            return None
        r = rows[0]
        return {"name": r[0], "quantity": r[1], "category": r[2], "barcode_type": r[3], "location": r[4]}

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
        await self._touch_item_last_used(name)
        return {"name": rows[0][0], "quantity": int(rows[0][1]), "status": rows[0][2]}

    async def move_item(self, name: str, to_location: str, from_location: str | None = None) -> dict:
        """Move an item to a new location. Deletes old STORED_IN, creates new one."""
        to_location = self._normalize_location(to_location) or to_location
        # Find the item
        q_find = """
        MATCH (i:Item)
        WHERE toLower(i.name) CONTAINS toLower($name)
        OPTIONAL MATCH (i)-[:STORED_IN]->(l:Location)
        RETURN i.name, l.path
        LIMIT 1
        """
        rows = await self.query(q_find, {"name": name})
        if not rows:
            return {"error": f"Item '{name}' not found"}
        item_name, old_location = rows[0][0], rows[0][1]
        # Delete old STORED_IN
        q_del = "MATCH (i:Item {name: $name})-[r:STORED_IN]->() DELETE r"
        await self.query(q_del, {"name": item_name})
        # Create new location + relationship
        await self.upsert_location(to_location)
        q_link = """
        MATCH (i:Item {name: $name})
        MATCH (l:Location {path: $loc})
        MERGE (i)-[:STORED_IN]->(l)
        """
        await self.query(q_link, {"name": item_name, "loc": to_location})
        # Update timestamp
        await self.query(
            "MATCH (i:Item {name: $name}) SET i.updated_at = $now",
            {"name": item_name, "now": _now()},
        )
        await self._touch_item_last_used(item_name)
        return {"name": item_name, "from_location": old_location, "to_location": to_location}

    async def find_similar_items(self, name: str) -> list[dict]:
        """Find inventory items whose name fuzzy-matches the given text."""
        q = """
        MATCH (i:Item)
        WHERE i.status IN ['active', null]
          AND toLower(i.name) CONTAINS toLower($name)
        OPTIONAL MATCH (i)-[:STORED_IN]->(l:Location)
        RETURN i.name, i.quantity, l.path
        LIMIT 5
        """
        rows = await self.query(q, {"name": name})
        return [{"name": r[0], "quantity": int(r[1] or 0), "location": r[2]} for r in (rows or [])]

    async def _touch_item_last_used(self, name: str) -> None:
        """Update last_used_at timestamp on an item (fire-and-forget)."""
        try:
            q = """
            MATCH (i:Item)
            WHERE toLower(i.name) CONTAINS toLower($name)
            SET i.last_used_at = $now
            """
            await self.query(q, {"name": name, "now": _now()})
        except Exception:
            pass

    async def query_unused_items(self, days: int | None = None) -> list[dict]:
        """Find items not used/mentioned for N days."""
        days = days or settings.inventory_unused_days
        cutoff = (_now_dt() - timedelta(days=days)).isoformat()
        q = """
        MATCH (i:Item)
        WHERE i.status = 'active'
          AND (i.last_used_at IS NULL OR i.last_used_at < $cutoff)
        OPTIONAL MATCH (i)-[:STORED_IN]->(l:Location)
        RETURN i.name, i.quantity, i.category, i.last_used_at, l.path
        ORDER BY i.last_used_at ASC
        LIMIT 20
        """
        rows = await self.query(q, {"cutoff": cutoff})
        return [{"name": r[0], "quantity": r[1], "category": r[2], "last_used_at": r[3], "location": r[4]} for r in rows]

    async def detect_duplicate_items(self) -> list[dict]:
        """Find potential duplicate items by name overlap."""
        q = """
        MATCH (a:Item), (b:Item)
        WHERE a.status = 'active' AND b.status = 'active'
          AND id(a) < id(b)
          AND (toLower(a.name) CONTAINS toLower(b.name)
               OR toLower(b.name) CONTAINS toLower(a.name))
        OPTIONAL MATCH (a)-[:STORED_IN]->(la:Location)
        OPTIONAL MATCH (b)-[:STORED_IN]->(lb:Location)
        RETURN a.name, a.quantity, la.path,
               b.name, b.quantity, lb.path
        LIMIT 20
        """
        rows = await self.query(q)
        results = []
        for r in rows:
            results.append({
                "item_a": {"name": r[0], "quantity": r[1], "location": r[2]},
                "item_b": {"name": r[3], "quantity": r[4], "location": r[5]},
            })
        return results

    async def detect_duplicate_items_vector(self) -> list[dict]:
        """Find potential duplicate items via vector similarity."""
        if not self._vector_service:
            return []
        q = "MATCH (i:Item) WHERE i.status = 'active' RETURN i.name"
        rows = await self.query(q)
        names = [r[0] for r in rows if r[0]]
        if len(names) < 2:
            return []

        duplicates = []
        checked: set[tuple[str, str]] = set()
        for name in names:
            if name in {n for pair in checked for n in pair}:
                continue
            try:
                results = await self._vector_service.search(
                    name, limit=3, source_type="file_inventory_item"
                )
                for r in results:
                    other = r["metadata"].get("text", "")
                    if other and other != name and r["score"] >= 0.8 and (name, other) not in checked:
                        duplicates.append({
                            "item_a": name,
                            "item_b": other,
                            "similarity": round(r["score"], 2),
                        })
                        checked.add((name, other))
                        checked.add((other, name))
            except Exception:
                continue
        return duplicates[:20]

    async def _create_generic(self, label: str, key_field: str, value: str, **props) -> None:
        if label in ("Knowledge", "Topic"):
            value = await self.resolve_entity_name(value, label, key_field)
        if label == "Knowledge" and not props.get("category"):
            content = props.get("content", "")
            props["category"] = self._guess_knowledge_category(value, content)
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

    _INTERNAL_PROPS = {"name_aliases", "created_at", "updated_at", "file_hash", "source"}

    def _clean_props(self, props: dict) -> dict:
        return {k: v for k, v in props.items() if k not in self._INTERNAL_PROPS}

    def _display_name(self, props: dict) -> str:
        """Return Arabic name (English) if available, else just English name."""
        name_ar = props.get("name_ar", "")
        name = props.get("name", props.get("title", "?"))
        return f"{name_ar} ({name})" if name_ar else name

    def _build_set_clause(self, props: dict, var: str = "p") -> str:
        filtered = {k: v for k, v in props.items() if v is not None and v != ""}
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
                    desc_parts.append(str(self._clean_props(node.properties)))
            if row[1] and row[3]:  # rel1, n1
                n1 = row[3]
                n1_name = self._display_name(n1.properties) if hasattr(n1, "properties") else str(n1)
                desc_parts.append(f"-[{row[1]}]-> [{row[2]}] {n1_name}")
            if row[4] and row[6]:  # rel2, n2
                n2 = row[6]
                n2_name = self._display_name(n2.properties) if hasattr(n2, "properties") else str(n2)
                desc_parts.append(f"-[{row[4]}]-> [{row[5]}] {n2_name}")
            if desc_parts:
                line = " ".join(desc_parts)
                if line not in seen:
                    seen.add(line)
                    parts.append(line)
        return "\n".join(parts[:20])

    def _format_graph_context_3hop(self, rows: list) -> str:
        """Format 3-hop graph context (10 columns per row)."""
        if not rows:
            return ""
        seen = set()
        parts = []
        for row in rows:
            desc_parts = []
            if row[0] and hasattr(row[0], "properties"):
                desc_parts.append(str(self._clean_props(row[0].properties)))
            if row[1] and row[3]:
                n1 = row[3]
                n1_name = self._display_name(n1.properties) if hasattr(n1, "properties") else str(n1)
                desc_parts.append(f"-[{row[1]}]-> [{row[2]}] {n1_name}")
            if row[4] and row[6]:
                n2 = row[6]
                n2_name = self._display_name(n2.properties) if hasattr(n2, "properties") else str(n2)
                desc_parts.append(f"-[{row[4]}]-> [{row[5]}] {n2_name}")
            if len(row) > 7 and row[7] and row[9]:
                n3 = row[9]
                n3_name = self._display_name(n3.properties) if hasattr(n3, "properties") else str(n3)
                desc_parts.append(f"-[{row[7]}]-> [{row[8]}] {n3_name}")
            if desc_parts:
                line = " ".join(desc_parts)
                if line not in seen:
                    seen.add(line)
                    parts.append(line)
        return "\n".join(parts[:30])


def _now() -> str:
    tz = timezone(timedelta(hours=get_settings().timezone_offset_hours))
    return datetime.now(tz).isoformat()


def _now_dt() -> datetime:
    tz = timezone(timedelta(hours=get_settings().timezone_offset_hours))
    return datetime.now(tz)
