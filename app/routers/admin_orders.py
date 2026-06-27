from __future__ import annotations
"""Router de gestión de órdenes para el panel admin."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth_utils import require_admin
from ..db import get_db_pool
from ..schemas import (
    OrderDetail,
    OrderItemDetail,
    OrderListResponse,
    OrderStatusUpdate,
    OrderSummary,
    ShippingAddressDetail,
)

router = APIRouter(prefix="/api/admin/orders", tags=["admin-orders"])

_VALID_STATUSES = {"pending", "paid", "preparing", "shipped", "delivered", "cancelled"}


@router.get("", response_model=OrderListResponse)
async def list_orders(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    order_status: str | None = Query(None, alias="status"),
    _: dict = Depends(require_admin),
) -> OrderListResponse:
    pool = get_db_pool()
    offset = (page - 1) * limit

    where_clauses: list[str] = []
    params: list = []
    idx = 1

    if order_status:
        where_clauses.append(f"o.status = ${idx}")
        params.append(order_status)
        idx += 1

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_row = await pool.fetchrow(
        f"SELECT COUNT(*) AS total FROM orders o {where_sql}", *params
    )
    total = count_row["total"] if count_row else 0

    params += [limit, offset]
    rows = await pool.fetch(
        f"""
        SELECT o.id, o.status, o.payment_method, o.total, o.shipping_cost,
               o.tracking_number, o.created_at
        FROM orders o
        {where_sql}
        ORDER BY o.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    items = [
        OrderSummary(
            id=r["id"],
            status=r["status"],
            payment_method=r["payment_method"],
            total=r["total"],
            shipping_cost=r["shipping_cost"],
            tracking_number=r.get("tracking_number"),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return OrderListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(order_id: int, _: dict = Depends(require_admin)) -> OrderDetail:
    pool = get_db_pool()
    order_row = await pool.fetchrow(
        """
        SELECT o.id, o.status, o.payment_method, o.subtotal, o.shipping_cost,
               o.total, o.notes, o.tracking_number, o.shipping_carrier,
               o.created_at, o.updated_at, o.shipping_address_id
        FROM orders o
        WHERE o.id = $1
        """,
        order_id,
    )
    if order_row is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    item_rows = await pool.fetch(
        """
        SELECT oi.id, oi.product_id, oi.product_name, oi.unit_price,
               oi.quantity, oi.subtotal, p.img_url AS image_url
        FROM order_items oi
        LEFT JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = $1
        """,
        order_id,
    )

    address = None
    if order_row["shipping_address_id"]:
        addr_row = await pool.fetchrow(
            "SELECT display_name, lat, lon, city, region, complement FROM shipping_addresses WHERE id = $1",
            order_row["shipping_address_id"],
        )
        if addr_row:
            address = ShippingAddressDetail(**dict(addr_row))

    return OrderDetail(
        id=order_row["id"],
        status=order_row["status"],
        payment_method=order_row["payment_method"],
        subtotal=order_row["subtotal"],
        shipping_cost=order_row["shipping_cost"],
        total=order_row["total"],
        notes=order_row.get("notes"),
        tracking_number=order_row.get("tracking_number"),
        shipping_carrier=order_row.get("shipping_carrier"),
        created_at=order_row["created_at"],
        updated_at=order_row["updated_at"],
        items=[OrderItemDetail(**dict(r)) for r in item_rows],
        shipping_address=address,
    )


@router.put("/{order_id}/status", response_model=dict)
async def update_order_status(
    order_id: int,
    body: OrderStatusUpdate,
    _: dict = Depends(require_admin),
) -> dict:
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Valores permitidos: {', '.join(_VALID_STATUSES)}",
        )
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        UPDATE orders
        SET status = $1,
            tracking_number = COALESCE($2, tracking_number),
            shipping_carrier = COALESCE($3, shipping_carrier),
            notes = COALESCE($4, notes),
            updated_at = NOW()
        WHERE id = $5
        RETURNING id, status, tracking_number
        """,
        body.status,
        body.tracking_number,
        body.shipping_carrier,
        body.notes,
        order_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return {"id": row["id"], "status": row["status"], "tracking_number": row["tracking_number"]}
