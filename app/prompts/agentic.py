THINK_SYSTEM = """You are a retrieval strategy planner for a personal life management system.
Given a user query (translated to English), decide the best retrieval strategy.

Available strategies:
- graph_financial: for expense/debt/budget queries → searches FalkorDB financial nodes
- graph_reminder: for reminders/appointments → searches FalkorDB reminder nodes
- graph_project: for project status/progress → searches FalkorDB project nodes
- graph_person: for people/relationships → searches FalkorDB person nodes with 2-hop context
- graph_task: for tasks/to-do items → searches FalkorDB task nodes
- vector: for knowledge/semantic search → searches Qdrant vector store
- hybrid: for queries needing both structured + semantic results → both graph + vector

Also generate 1-3 search queries optimized for the chosen strategy.

Respond with ONLY a JSON object:
{
  "strategy": "<strategy>",
  "search_queries": ["query1", "query2"],
  "reasoning": "brief explanation of why this strategy"
}"""


def build_think(query_en: str) -> list[dict]:
    return [
        {"role": "system", "content": THINK_SYSTEM},
        {"role": "user", "content": f"User query: {query_en}"},
    ]


REFLECT_SYSTEM = """You are a retrieval quality evaluator for a personal life management system.
Given a user query and the retrieved context chunks, evaluate:
1. Whether the retrieved information is sufficient to answer the query
2. A relevance score (0.0-1.0) for each chunk

Respond with ONLY a JSON object:
{
  "sufficient": true/false,
  "chunk_scores": [
    {"index": 0, "score": 0.85, "reason": "directly answers the query"},
    {"index": 1, "score": 0.3, "reason": "tangentially related"}
  ],
  "retry_strategy": "vector/graph_financial/graph_person/null (only if sufficient=false, suggest alternative strategy)"
}"""


def build_reflect(query_en: str, chunks: list[str]) -> list[dict]:
    chunks_text = "\n\n".join(
        f"[Chunk {i}]: {c}" for i, c in enumerate(chunks)
    )
    return [
        {"role": "system", "content": REFLECT_SYSTEM},
        {
            "role": "user",
            "content": f"User query: {query_en}\n\nRetrieved chunks:\n{chunks_text}",
        },
    ]
