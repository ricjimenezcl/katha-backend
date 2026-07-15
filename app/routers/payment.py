from __future__ import annotations
"""Router de pagos Transbank Webpay Plus."""

import logging
import urllib.parse
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from transbank.common.integration_type import IntegrationType
from transbank.common.options import WebpayOptions
from transbank.webpay.webpay_plus.transaction import Transaction

from ..config import settings
from ..db import get_db_pool
from ..schemas import CheckoutPayload, OrderCreated

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment", tags=["payment"])

# ── Configuración Transbank ────────────────────────────────────────────────────

def _build_transaction() -> Transaction:
    """Construye la instancia de Transaction según el entorno."""
    env = settings.transbank_environment.lower()
    if env == "production":
        options = WebpayOptions(
            commerce_code=settings.transbank_commerce_code,
            api_key=settings.transbank_api_key,
            integration_type=IntegrationType.LIVE,
        )
    else:
        # Credenciales de integración por defecto si no hay variables de entorno
        commerce_code = settings.transbank_commerce_code or "597055555532"
        api_key = settings.transbank_api_key or (
            "579B532A7440BB0116B0A3D54BF3B38E"
        )
        options = WebpayOptions(
            commerce_code=commerce_code,
            api_key=api_key,
            integration_type=IntegrationType.TEST,
        )
    return Transaction(options)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _return_url(request: Request) -> str:
    """URL pública de retorno para Transbank (backend)."""
    base = settings.render_external_url.rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/api/payment/transbank/return"


def _frontend_result_url(status: str, order_id: int | None = None) -> str:
    """URL del frontend para mostrar el resultado al usuario."""
    base_url = settings.frontend_url.rstrip("/")
    params: dict[str, Any] = {"status": status}
    if order_id is not None:
        params["order_id"] = order_id
    return f"{base_url}/checkout/result?{urllib.parse.urlencode(params)}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/transbank/init", response_model=dict)
async def transbank_init(payload: CheckoutPayload, request: Request) -> dict:
    """
    1. Valida stock de todos los ítems.
    2. Crea la orden en estado 'pending' (sin deducir stock todavía).
    3. Llama a Transbank para iniciar la transacción.
    4. Devuelve { url, token } al frontend.
    """
    pool = get_db_pool()

    # ── Validar stock ─────────────────────────────────────────────────────────
    async with pool.acquire() as conn:
        for item in payload.items:
            row = await conn.fetchrow(
                "SELECT stock FROM products WHERE id = $1 AND active = true",
                item.productId,
            )
            if row is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Producto no encontrado: {item.name}",
                )
            if row["stock"] < item.quantity:
                raise HTTPException(
                    status_code=422,
                    detail=f"Sin stock suficiente para '{item.name}' (disponible: {row['stock']})",
                )

        # ── Crear dirección de envío ──────────────────────────────────────────
        async with conn.transaction():
            addr_row = await conn.fetchrow(
                """
                INSERT INTO shipping_addresses (
                  display_name, lat, lon, city, region, complement
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                payload.shippingAddress.display_name,
                float(payload.shippingAddress.lat),
                float(payload.shippingAddress.lon),
                payload.shippingAddress.commune,
                payload.shippingAddress.region,
                payload.shippingAddress.complement,
            )
            if addr_row is None:
                raise HTTPException(status_code=500, detail="No se pudo crear dirección")
            shipping_address_id = addr_row["id"]

            # ── Crear orden (estado pending) ──────────────────────────────────
            order_row = await conn.fetchrow(
                """
                INSERT INTO orders (
                  payment_method, subtotal, shipping_cost, total,
                  shipping_address_id, guest_email, status
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pending')
                RETURNING id
                """,
                payload.paymentMethod,
                payload.subtotal,
                payload.shippingCost,
                payload.amount,
                shipping_address_id,
                payload.guestEmail,
            )
            if order_row is None:
                raise HTTPException(status_code=500, detail="No se pudo crear orden")
            order_id = order_row["id"]

            # ── Crear ítems de la orden ───────────────────────────────────────
            for item in payload.items:
                await conn.execute(
                    """
                    INSERT INTO order_items (
                      order_id, product_id, product_name, unit_price, quantity, subtotal
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    order_id,
                    item.productId,
                    item.name,
                    item.price,
                    item.quantity,
                    item.price * item.quantity,
                )

            # ── Iniciar transacción Transbank ─────────────────────────────────
            buy_order = f"KATHA-{order_id}"
            session_id = f"sess-{order_id}"
            return_url = _return_url(request)

            try:
                tx = _build_transaction()
                tb_response = tx.create(
                    buy_order=buy_order,
                    session_id=session_id,
                    amount=payload.amount,
                    return_url=return_url,
                )
            except Exception as exc:
                log.exception("Error al iniciar transacción Transbank: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="Error al conectar con Transbank. Intenta nuevamente.",
                ) from exc

            token_ws: str = tb_response.token
            webpay_url: str = tb_response.url

            # ── Guardar token en payment_transactions ─────────────────────────
            await conn.execute(
                """
                INSERT INTO payment_transactions (
                  order_id, gateway, amount, currency,
                  token_ws, return_url, status
                ) VALUES ($1, 'webpay', $2, $3, $4, $5, 'initiated')
                """,
                order_id,
                payload.amount,
                payload.currency,
                token_ws,
                return_url,
            )

    return {"url": webpay_url, "token": token_ws, "orderId": order_id}


@router.post("/transbank/return")
@router.get("/transbank/return")
async def transbank_return(
    request: Request,
    token_ws: str | None = None,
    TBK_TOKEN: str | None = None,
    TBK_ORDEN_COMPRA: str | None = None,
) -> RedirectResponse:
    """
    Transbank redirige aquí después del pago.
    Confirma la transacción, actualiza stock y redirige al frontend.
    """
    pool = get_db_pool()

    # Pago cancelado por el usuario
    if TBK_TOKEN and not token_ws:
        log.info("Pago cancelado por usuario: TBK_TOKEN=%s", TBK_TOKEN)
        # Buscar orden por token y marcarla cancelada
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT order_id FROM payment_transactions WHERE token_ws = $1",
                TBK_TOKEN,
            )
            if row:
                await conn.execute(
                    "UPDATE orders SET status='cancelled', updated_at=NOW() WHERE id=$1",
                    row["order_id"],
                )
                await conn.execute(
                    "UPDATE payment_transactions SET status='cancelled', updated_at=NOW() WHERE token_ws=$1",
                    TBK_TOKEN,
                )
        return RedirectResponse(
            url=_frontend_result_url("cancelled"),
            status_code=303,
        )

    # Timeout de Transbank
    if not token_ws:
        log.warning("Retorno de Transbank sin token_ws ni TBK_TOKEN")
        return RedirectResponse(
            url=_frontend_result_url("error"),
            status_code=303,
        )

    # ── Confirmar transacción ─────────────────────────────────────────────────
    try:
        tx = _build_transaction()
        commit_response = tx.commit(token_ws)
    except Exception as exc:
        log.exception("Error al confirmar transacción Transbank: %s", exc)
        return RedirectResponse(
            url=_frontend_result_url("error"),
            status_code=303,
        )

    # VCI de Transbank: TSY = aprobado, TSN = rechazado, etc.
    response_code: int = commit_response.response_code
    is_approved: bool = response_code == 0

    # Obtener orden desde la DB
    async with pool.acquire() as conn:
        pt_row = await conn.fetchrow(
            "SELECT order_id FROM payment_transactions WHERE token_ws = $1",
            token_ws,
        )
        if pt_row is None:
            log.error("No se encontró payment_transaction para token_ws=%s", token_ws)
            return RedirectResponse(url=_frontend_result_url("error"), status_code=303)

        order_id: int = pt_row["order_id"]

        if is_approved:
            # ── Deducir stock SOLO si pago aprobado ────────────────────────
            items_rows = await conn.fetch(
                "SELECT product_id, quantity, product_name FROM order_items WHERE order_id = $1",
                order_id,
            )
            async with conn.transaction():
                for item in items_rows:
                    updated = await conn.fetchrow(
                        """
                        UPDATE products
                        SET stock = stock - $1, updated_at = NOW()
                        WHERE id = $2 AND stock >= $1
                        RETURNING id, stock
                        """,
                        item["quantity"],
                        item["product_id"],
                    )
                    if updated is None:
                        # Sin stock: la venta igual se confirma (no se cancela) pero se registra
                        log.warning(
                            "Stock insuficiente post-pago para product_id=%s, qty=%s",
                            item["product_id"], item["quantity"]
                        )
                        # Deducir hasta 0 sin fallar la venta
                        await conn.execute(
                            "UPDATE products SET stock=0, updated_at=NOW() WHERE id=$1",
                            item["product_id"],
                        )

                    await conn.execute(
                        """
                        INSERT INTO inventory_movements (product_id, quantity_change, reason)
                        VALUES ($1, $2, 'sale')
                        """,
                        item["product_id"],
                        -item["quantity"],
                    )

                # Actualizar orden a pagada
                await conn.execute(
                    "UPDATE orders SET status='paid', updated_at=NOW() WHERE id=$1",
                    order_id,
                )

                # Actualizar payment_transaction
                card_detail = commit_response.card_detail
                await conn.execute(
                    """
                    UPDATE payment_transactions
                    SET status='approved',
                        webpay_status=$2,
                        card_last_four=$3,
                        installments_number=$4,
                        raw_response=$5,
                        updated_at=NOW()
                    WHERE token_ws=$1
                    """,
                    token_ws,
                    commit_response.status,
                    (card_detail.card_number[-4:] if card_detail and card_detail.card_number else None),
                    commit_response.installments_number or 0,
                    str(vars(commit_response)),
                )

            log.info("Pago aprobado. order_id=%s", order_id)
            return RedirectResponse(
                url=_frontend_result_url("success", order_id),
                status_code=303,
            )

        else:
            # Pago rechazado
            async with conn.transaction():
                await conn.execute(
                    "UPDATE orders SET status='cancelled', updated_at=NOW() WHERE id=$1",
                    order_id,
                )
                await conn.execute(
                    """
                    UPDATE payment_transactions
                    SET status='rejected', webpay_status=$2, raw_response=$3, updated_at=NOW()
                    WHERE token_ws=$1
                    """,
                    token_ws,
                    commit_response.status,
                    str(vars(commit_response)),
                )

            log.info("Pago rechazado (code=%s). order_id=%s", response_code, order_id)
            return RedirectResponse(
                url=_frontend_result_url("rejected"),
                status_code=303,
            )
