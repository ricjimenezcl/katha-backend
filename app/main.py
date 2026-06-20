from contextlib import asynccontextmanager
import logging
import time
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import close_db_pool, get_db_pool, init_db_pool
from .schemas import CheckoutPayload, GeocodingResponse, GeocodingResult, OrderCreated, ShippingRate

logger = logging.getLogger(__name__)

CACHE_TTL_MS = 5 * 60 * 1000
_geocode_cache: dict[str, dict[str, Any]] = {}
REVERSE_CACHE_TTL_MS = 10 * 60 * 1000
_reverse_geocode_cache: dict[str, dict[str, Any]] = {}


def _build_geocode_cache_key(q: str, country: str) -> str:
    return f"{q.strip().lower()}|{country.strip().lower()}"


def _build_reverse_cache_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _parse_nominatim_result(item: dict[str, Any]) -> GeocodingResult:
    address = item.get("address") or {}
    text = (
        address.get("road")
        or address.get("pedestrian")
        or address.get("footway")
        or item.get("name")
        or (item.get("display_name") or "").split(",")[0].strip()
    )
    number = address.get("house_number") or ""

    return GeocodingResult(
        place_name=item.get("display_name") or text,
        text=text,
        address=number,
        center=[float(item.get("lon") or 0), float(item.get("lat") or 0)],
        relevance=float(item.get("importance") or 0.5),
        place_type=[str(item.get("type") or "address")],
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db_pool()
    yield
    await close_db_pool()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get(
    "/api/providers/geocoding/search",
    responses={502: {"description": "Fallo servicio de geocoding"}},
)
async def geocoding_search(
    q: Annotated[str, Query(min_length=2)],
    country: Annotated[str, Query()] = "cl",
) -> GeocodingResponse:
    cache_key = _build_geocode_cache_key(q, country)
    cached = _geocode_cache.get(cache_key)
    now = time.time() * 1000

    if cached and (now - cached["ts"]) < CACHE_TTL_MS:
        return GeocodingResponse(source="cache", results=cached["results"])

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": q,
        "countrycodes": country,
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": "8",
    }
    headers = {
        "Accept-Language": "es",
        "User-Agent": settings.nominatim_user_agent,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "geocoding provider error",
                    request=resp.request,
                    response=resp,
                )
            raw = resp.json() or []
    except Exception as exc:
        logger.warning("Geocoding provider failed, using fallback: %s", exc)
        if cached:
            return GeocodingResponse(source="cache-stale", results=cached["results"])
        return GeocodingResponse(source="fallback", results=[])

    results = [_parse_nominatim_result(item) for item in raw]
    _geocode_cache[cache_key] = {"ts": now, "results": results}

    if len(_geocode_cache) > 200:
        first_key = next(iter(_geocode_cache.keys()))
        _geocode_cache.pop(first_key, None)

    return GeocodingResponse(source="api", results=results)


@app.get(
    "/api/geocoding/reverse",
    responses={502: {"description": "Fallo servicio de reverse geocoding"}},
)
async def geocoding_reverse(
    lat: Annotated[float, Query()],
    lon: Annotated[float, Query()],
) -> dict[str, Any]:
    cache_key = _build_reverse_cache_key(lat, lon)
    cached = _reverse_geocode_cache.get(cache_key)
    now = time.time() * 1000

    if cached and (now - cached["ts"]) < REVERSE_CACHE_TTL_MS:
        return cached["payload"]

    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": str(lat),
        "lon": str(lon),
        "format": "jsonv2",
        "addressdetails": "1",
    }
    headers = {
        "Accept-Language": "es",
        "User-Agent": settings.nominatim_user_agent,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "reverse geocoding provider error",
                    request=resp.request,
                    response=resp,
                )
            raw = resp.json() or {}
    except Exception as exc:
        logger.warning("Reverse geocoding provider failed, using fallback: %s", exc)
        if cached:
            return cached["payload"]
        return {
            "features": [
                {
                    "properties": {
                        "formatted": "Ubicación desconocida",
                    }
                }
            ]
        }

    formatted = raw.get("display_name") or "Ubicación desconocida"
    payload = {
        "features": [
            {
                "properties": {
                    "formatted": formatted,
                }
            }
        ]
    }

    _reverse_geocode_cache[cache_key] = {"ts": now, "payload": payload}
    if len(_reverse_geocode_cache) > 200:
        first_key = next(iter(_reverse_geocode_cache.keys()))
        _reverse_geocode_cache.pop(first_key, None)

    return payload


@app.get("/api/shipping-rates")
async def shipping_rates() -> list[ShippingRate]:
    pool = get_db_pool()
    query = """
    SELECT region_id, region_name, cost
    FROM shipping_rates
    WHERE active = true
    ORDER BY region_id
    """
    rows = await pool.fetch(query)
    return [ShippingRate(**dict(r)) for r in rows]


@app.post(
    "/api/orders",
    responses={500: {"description": "Error creando orden/transacción"}},
)
async def create_order(payload: CheckoutPayload) -> OrderCreated:
    pool = get_db_pool()

    async with pool.acquire() as conn:
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

            order_row = await conn.fetchrow(
                """
                INSERT INTO orders (
                  payment_method, subtotal, shipping_cost, total, shipping_address_id
                ) VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                payload.paymentMethod,
                payload.subtotal,
                payload.shippingCost,
                payload.amount,
                shipping_address_id,
            )
            if order_row is None:
                raise HTTPException(status_code=500, detail="No se pudo crear orden")
            order_id = order_row["id"]

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

            tx_row = await conn.fetchrow(
                """
                INSERT INTO payment_transactions (order_id, gateway, amount, currency)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                order_id,
                payload.paymentMethod,
                payload.amount,
                payload.currency,
            )
            if tx_row is None:
                raise HTTPException(status_code=500, detail="No se pudo crear transacción")

            return OrderCreated(orderId=order_id, transactionId=tx_row["id"])
