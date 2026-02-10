from fastapi import APIRouter, Request

from app.models.schemas import (
    InventoryItemRequest,
    InventoryLocationUpdate,
    InventoryQuantityUpdate,
)

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


@router.put("/item/{name}/location")
async def update_item_location(name: str, req: InventoryLocationUpdate, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.update_item(name, location=req.location)


@router.put("/item/{name}/quantity")
async def update_item_quantity(name: str, req: InventoryQuantityUpdate, request: Request):
    graph = request.app.state.retrieval.graph
    return await graph.update_item(name, quantity=req.quantity)
