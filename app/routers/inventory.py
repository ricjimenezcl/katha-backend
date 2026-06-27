from __future__ import annotations
"""Router de control de inventario."""
from fastapi import APIRouter, Depends, HTTPException

from ..auth_utils import require_admin
from ..db import get_db_pool
from ..schemas import InventoryItem, InventoryListResponse, MovementRecord, StockAdjust

router = APIRouter(prefix="/api/admin/inventory", tags=["inventory"])

_LOW_STOCK_THRESHOLD = 5


def _stock_status(stock: int) -> str:
    if stock <= 0:
        return "out"
    if stock <= _LOW_STOCK_THRESHOLD:
        return "low"
    return "ok"


@router.get("", response_model=InventoryListResponse)
async def list_inventory(_: dict = Depends(require_admin)) -> InventoryListResponse:
    pool = get_db_pool()
    rows = await pool.fetch(
        """
        SELECT p.id, p.name, p.img_url AS image_url, p.stock, c.slug AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.active = TRUE
        ORDER BY p.stock ASC, p.name ASC
        """
    )
    items = [
        InventoryItem(
            id=r["id"],
            name=r["name"],
            category=r["category"] or "",
            image_url=r.get("image_url"),
            stock=r["stock"],
            stock_status=_stock_status(r["stock"]),
        )
        for r in rows
    ]
    return InventoryListResponse(items=items, total=len(items))


@router.post("/adjust", response_model=dict)
async def adjust_stock(body: StockAdjust, admin: dict = Depends(require_admin)) -> dict:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            product = await conn.fetchrow(
                "SELECT id, stock FROM products WHERE id = $1", body.product_id
            )
            if product is None:
                raise HTTPException(status_code=404, detail="Producto no encontrado")

            new_stock = product["stock"] + body.quantity_change
            if new_stock < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stock insuficiente. Stock actual: {product['stock']}",
                )

            await conn.execute(
                "UPDATE products SET stock = $1, updated_at = NOW() WHERE id = $2",
                new_stock,
                body.product_id,
            )
            await conn.execute(
                """
                INSERT INTO inventory_movements (product_id, quantity_change, reason, created_by)
                VALUES ($1, $2, $3, $4)
                """,
                body.product_id,
                body.quantity_change,
                body.reason,
                int(admin["sub"]),
            )
    return {"product_id": body.product_id, "new_stock": new_stock}


@router.get("/movements", response_model=list[MovementRecord])
async def list_movements(
    product_id: int | None = None,
    _: dict = Depends(require_admin),
) -> list[MovementRecord]:
    pool = get_db_pool()
    if product_id:
        rows = await pool.fetch(
            """
            SELECT im.id, im.product_id, p.name AS product_name,
                   im.quantity_change, im.reason, im.created_at
            FROM inventory_movements im
            JOIN products p ON p.id = im.product_id
            WHERE im.product_id = $1
            ORDER BY im.created_at DESC
            LIMIT 100
            """,
            product_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT im.id, im.product_id, p.name AS product_name,
                   im.quantity_change, im.reason, im.created_at
            FROM inventory_movements im
            JOIN products p ON p.id = im.product_id
            ORDER BY im.created_at DESC
            LIMIT 200
            """
        )
    return [MovementRecord(**dict(r)) for r in rows]
