"""Graph visualization — JSON export, schema, stats, and server-side PNG generation."""

import io
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

# Color palette for node types
_NODE_COLORS = {
    "Person": "#4A90D9",
    "Project": "#E8943A",
    "Task": "#5CB85C",
    "Expense": "#D9534F",
    "Debt": "#F0AD4E",
    "Reminder": "#9B59B6",
    "Company": "#3498DB",
    "Item": "#1ABC9C",
    "Knowledge": "#2ECC71",
    "Topic": "#95A5A6",
    "Tag": "#BDC3C7",
    "Sprint": "#E74C3C",
    "Idea": "#F39C12",
    "FocusSession": "#8E44AD",
    "Location": "#16A085",
}


class GraphImageRequest(BaseModel):
    entity_type: Optional[str] = None
    center: Optional[str] = None
    hops: int = 2
    width: int = 1200
    height: int = 800
    limit: int = 500


@router.get("/export")
async def graph_export(
    request: Request,
    entity_type: Optional[str] = Query(None),
    center: Optional[str] = Query(None),
    hops: int = Query(2, ge=1, le=5),
    limit: int = Query(500, ge=1, le=5000),
):
    """Export subgraph as JSON (nodes + edges)."""
    graph = request.app.state.retrieval.graph

    if center:
        data = await _export_ego_graph(graph, center, hops, limit)
    elif entity_type:
        data = await _export_by_type(graph, entity_type, limit)
    else:
        data = await _export_full_graph(graph, limit)

    return data


@router.get("/schema")
async def graph_schema(request: Request):
    """Return node labels, relationship types, and counts."""
    graph = request.app.state.retrieval.graph

    # Node labels + counts
    rows = await graph.query("MATCH (n) RETURN labels(n) AS lbls, count(n) AS cnt")
    label_counts = {}
    for row in rows:
        labels = row[0]
        count = row[1]
        label = labels[0] if isinstance(labels, list) and labels else str(labels)
        label_counts[label] = label_counts.get(label, 0) + count

    # Relationship types + counts
    rows = await graph.query("MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS cnt")
    rel_counts = {}
    for row in rows:
        rel_counts[row[0]] = row[1]

    return {
        "node_labels": label_counts,
        "relationship_types": rel_counts,
        "total_nodes": sum(label_counts.values()),
        "total_edges": sum(rel_counts.values()),
    }


@router.get("/stats")
async def graph_stats(request: Request):
    """Return total nodes, edges, and counts by type."""
    graph = request.app.state.retrieval.graph

    rows = await graph.query("MATCH (n) RETURN labels(n) AS lbls, count(n) AS cnt")
    by_type = {}
    total_nodes = 0
    for row in rows:
        labels = row[0]
        count = row[1]
        label = labels[0] if isinstance(labels, list) and labels else str(labels)
        by_type[label] = by_type.get(label, 0) + count
        total_nodes += count

    rows = await graph.query("MATCH ()-[r]->() RETURN count(r) AS cnt")
    total_edges = rows[0][0] if rows else 0

    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "by_type": by_type,
    }


@router.post("/image")
async def graph_image(req: GraphImageRequest, request: Request):
    """Generate PNG image of the graph."""
    graph = request.app.state.retrieval.graph

    if req.center:
        data = await _export_ego_graph(graph, req.center, req.hops, req.limit)
    elif req.entity_type:
        data = await _export_by_type(graph, req.entity_type, req.limit)
    else:
        data = await _export_full_graph(graph, req.limit)

    png_bytes = _render_graph_image(data, req.width, req.height)
    return Response(content=png_bytes, media_type="image/png")


# --- Internal helpers ---

async def _export_full_graph(graph, limit: int) -> dict:
    nodes = []
    node_ids = set()

    rows = await graph.query(
        "MATCH (n) RETURN id(n) AS nid, labels(n) AS lbls, properties(n) AS props LIMIT $limit",
        {"limit": limit},
    )
    for row in rows:
        nid = row[0]
        labels = row[1]
        props = row[2] if row[2] else {}
        label = labels[0] if isinstance(labels, list) and labels else str(labels)
        node_ids.add(nid)
        nodes.append({
            "id": nid,
            "label": props.get("name", props.get("description", props.get("title", str(nid)))),
            "type": label,
            "properties": props,
        })

    edges = []
    rows = await graph.query(
        "MATCH (a)-[r]->(b) RETURN id(a), type(r), properties(r), id(b) LIMIT $limit",
        {"limit": limit},
    )
    for row in rows:
        src_id, rel_type, rel_props, tgt_id = row[0], row[1], row[2] or {}, row[3]
        if src_id in node_ids and tgt_id in node_ids:
            edges.append({
                "source": src_id,
                "target": tgt_id,
                "type": rel_type,
                "properties": rel_props,
            })

    return {"nodes": nodes, "edges": edges}


async def _export_by_type(graph, entity_type: str, limit: int) -> dict:
    nodes = []
    node_ids = set()

    rows = await graph.query(
        f"MATCH (n:{entity_type}) RETURN id(n) AS nid, labels(n) AS lbls, properties(n) AS props LIMIT $limit",
        {"limit": limit},
    )
    for row in rows:
        nid, labels, props = row[0], row[1], row[2] or {}
        label = labels[0] if isinstance(labels, list) and labels else str(labels)
        node_ids.add(nid)
        nodes.append({
            "id": nid,
            "label": props.get("name", props.get("description", str(nid))),
            "type": label,
            "properties": props,
        })

    edges = []
    rows = await graph.query(
        f"MATCH (a:{entity_type})-[r]-(b) RETURN id(a), type(r), properties(r), id(b), labels(b), properties(b) LIMIT $limit",
        {"limit": limit},
    )
    for row in rows:
        src_id, rel_type, rel_props, tgt_id = row[0], row[1], row[2] or {}, row[3]
        tgt_labels = row[4]
        tgt_props = row[5] or {}
        # Add connected nodes that aren't already in the set
        if tgt_id not in node_ids:
            tgt_label = tgt_labels[0] if isinstance(tgt_labels, list) and tgt_labels else str(tgt_labels)
            node_ids.add(tgt_id)
            nodes.append({
                "id": tgt_id,
                "label": tgt_props.get("name", tgt_props.get("description", str(tgt_id))),
                "type": tgt_label,
                "properties": tgt_props,
            })
        edges.append({
            "source": src_id,
            "target": tgt_id,
            "type": rel_type,
            "properties": rel_props,
        })

    return {"nodes": nodes, "edges": edges}


async def _export_ego_graph(graph, center_name: str, hops: int, limit: int) -> dict:
    nodes = []
    node_ids = set()

    # Find center node and connected nodes within N hops
    rows = await graph.query(
        "MATCH (c) WHERE c.name = $name "
        f"OPTIONAL MATCH path = (c)-[*1..{hops}]-(n) "
        "WITH c, n "
        "UNWIND [c, n] AS node "
        "WITH DISTINCT node WHERE node IS NOT NULL "
        "RETURN id(node), labels(node), properties(node) LIMIT $limit",
        {"name": center_name, "limit": limit},
    )
    for row in rows:
        nid, labels, props = row[0], row[1], row[2] or {}
        label = labels[0] if isinstance(labels, list) and labels else str(labels)
        if nid not in node_ids:
            node_ids.add(nid)
            nodes.append({
                "id": nid,
                "label": props.get("name", props.get("description", str(nid))),
                "type": label,
                "properties": props,
            })

    edges = []
    if node_ids:
        rows = await graph.query(
            "MATCH (a)-[r]->(b) "
            "WHERE id(a) IN $ids AND id(b) IN $ids "
            "RETURN id(a), type(r), properties(r), id(b) LIMIT $limit",
            {"ids": list(node_ids), "limit": limit},
        )
        for row in rows:
            edges.append({
                "source": row[0],
                "target": row[3],
                "type": row[1],
                "properties": row[2] or {},
            })

    return {"nodes": nodes, "edges": edges}


def _render_graph_image(data: dict, width: int, height: int) -> bytes:
    """Render graph data as PNG using networkx + matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    # Try to use Arabic font
    try:
        matplotlib.rcParams["font.family"] = "Noto Sans Arabic"
    except Exception:
        try:
            matplotlib.rcParams["font.family"] = "DejaVu Sans"
        except Exception:
            pass

    G = nx.DiGraph()

    for node in data.get("nodes", []):
        G.add_node(node["id"], label=node["label"], node_type=node["type"])

    for edge in data.get("edges", []):
        G.add_edge(edge["source"], edge["target"], rel_type=edge["type"])

    if not G.nodes:
        # Empty graph — return minimal PNG
        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        ax.text(0.5, 0.5, "No data", ha="center", va="center", fontsize=20)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)

    # Layout
    k = max(0.5, 2.0 / (len(G.nodes) ** 0.5)) if G.nodes else 1.0
    pos = nx.spring_layout(G, k=k, iterations=50, seed=42)

    # Node colors
    node_colors = []
    for n in G.nodes:
        nt = G.nodes[n].get("node_type", "")
        node_colors.append(_NODE_COLORS.get(nt, "#7F8C8D"))

    # Draw
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=300, alpha=0.9, ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#CCCCCC", arrows=True, arrowsize=12, alpha=0.6, ax=ax)

    # Labels
    labels = {n: G.nodes[n].get("label", str(n))[:20] for n in G.nodes}
    nx.draw_networkx_labels(G, pos, labels, font_size=7, ax=ax)

    # Edge labels (relationship types)
    edge_labels = {(u, v): G.edges[u, v].get("rel_type", "") for u, v in G.edges}
    nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=5, font_color="#888888", ax=ax)

    ax.axis("off")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()
