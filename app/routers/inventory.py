from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.models.schemas import (
    InventoryItemRequest,
    InventoryLocationUpdate,
    InventoryQuantityUpdate,
)

settings = get_settings()

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/")
async def list_inventory(
    request: Request, search: str | None = None, category: str | None = None
):
    graph = request.app.state.retrieval.graph
    text = await graph.query_inventory(search=search, category=category)
    return {"items": text}


@router.get("/summary")
async def inventory_summary(request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.query_inventory_summary()


@router.post("/item")
async def create_or_update_item(req: InventoryItemRequest, request: Request):
    graph = request.app.state.retrieval.graph
    result = await graph.upsert_item(
        name=req.name,
        quantity=req.quantity,
        location=req.location,
        category=req.category,
        condition=req.condition,
        brand=req.brand,
        description=req.description,
    )
    return result


@router.get("/by-barcode/{barcode}")
async def get_item_by_barcode(barcode: str, request: Request):
    """Find inventory item by barcode value."""
    graph = request.app.state.retrieval.graph
    item = await graph.find_item_by_barcode(barcode)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/by-file/{file_hash}")
async def get_item_by_file(file_hash: str, request: Request):
    """Find inventory item linked to a file by hash."""
    graph = request.app.state.retrieval.graph
    return await graph.find_item_by_file_hash(file_hash)


@router.put("/item/{name}/location")
async def update_item_location(name: str, req: InventoryLocationUpdate, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.update_item(name, location=req.location)


@router.put("/item/{name}/quantity")
async def update_item_quantity(name: str, req: InventoryQuantityUpdate, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.update_item(name, quantity=req.quantity)


@router.get("/report")
async def inventory_report(request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.query_inventory_report()


@router.get("/duplicates")
async def detect_duplicates(request: Request, method: str = "name"):
    graph = request.app.state.retrieval.graph
    if method == "vector":
        return {"duplicates": await graph.detect_duplicate_items_vector()}
    return {"duplicates": await graph.detect_duplicate_items()}


@router.get("/unused")
async def list_unused_items(request: Request, days: int | None = None):
    graph = request.app.state.retrieval.graph
    items = await graph.query_unused_items(days)
    return {"items": items, "threshold_days": days or settings.inventory_unused_days}


@router.post("/search-similar")
async def search_similar_items(request: Request, body: dict):
    """Search for similar inventory items by text description."""
    description = body.get("description", "")
    if not description:
        return {"results": []}
    vector = request.app.state.retrieval.vector
    results = await vector.search(description, limit=5, source_type="file_inventory_item")
    return {
        "results": [
            {"text": r["text"][:300], "score": round(r["score"], 2), "metadata": r["metadata"]}
            for r in results if r["score"] >= 0.4
        ]
    }
