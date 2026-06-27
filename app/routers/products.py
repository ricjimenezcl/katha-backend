from __future__ import annotations
"""Router de productos: CRUD admin + listado público + upload Cloudinary."""
import io
from typing import Annotated

import cloudinary
import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from ..auth_utils import require_admin
from ..config import settings
from ..db import get_db_pool
from ..schemas import (
    ImageUploadResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(tags=["products"])

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _init_cloudinary() -> None:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def _row_to_product(row: dict) -> ProductResponse:
    return ProductResponse(
        id=row["id"],
        name=row["name"],
        description=row.get("energy_description"),
        price=row["price"],
        category=row.get("category") or "",
        image_url=row.get("img_url"),
        cloudinary_public_id=row.get("cloudinary_public_id"),
        stock=row["stock"],
        active=row["active"],
        tag=row.get("tag"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Público ────────────────────────────────────────────────────────────────

@router.get("/api/products", response_model=ProductListResponse)
async def list_products_public(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    category: str | None = None,
    search: str | None = None,
) -> ProductListResponse:
    pool = get_db_pool()
    offset = (page - 1) * limit

    where_clauses = ["p.active = TRUE", "p.stock > 0"]
    params: list = []
    idx = 1

    if category:
        where_clauses.append(f"c.slug = ${idx}")
        params.append(category)
        idx += 1
    if search:
        where_clauses.append(f"p.name ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where_sql = " AND ".join(where_clauses)

    count_row = await pool.fetchrow(
        f"""
        SELECT COUNT(*) AS total FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE {where_sql}
        """,
        *params,
    )
    total = count_row["total"] if count_row else 0

    params += [limit, offset]
    rows = await pool.fetch(
        f"""
        SELECT p.id, p.name, p.energy_description, p.price, p.tag,
               p.img_url, p.cloudinary_public_id, p.stock, p.active,
               p.created_at, p.updated_at,
               c.slug AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE {where_sql}
        ORDER BY p.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    return ProductListResponse(
        items=[_row_to_product(dict(r)) for r in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/api/products/{product_id}", response_model=ProductResponse)
async def get_product_public(product_id: int) -> ProductResponse:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT p.id, p.name, p.energy_description, p.price, p.tag,
               p.img_url, p.cloudinary_public_id, p.stock, p.active,
               p.created_at, p.updated_at,
               c.slug AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.id = $1 AND p.active = TRUE
        """,
        product_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    return _row_to_product(dict(row))


# ── Admin ──────────────────────────────────────────────────────────────────

@router.post("/api/admin/products/upload-image", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    _: dict = Depends(require_admin),
) -> ImageUploadResponse:
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido. Use JPEG, PNG, WebP o GIF.")

    content = await file.read()
    if len(content) > _MAX_SIZE:
        raise HTTPException(status_code=400, detail="El archivo excede el tamaño máximo de 5 MB.")

    _init_cloudinary()
    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(content),
            folder="katha/products",
            resource_type="image",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al subir imagen: {exc}") from exc

    return ImageUploadResponse(url=result["secure_url"], public_id=result["public_id"])


@router.get("/api/admin/products", response_model=ProductListResponse)
async def list_products_admin(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    category: str | None = None,
    search: str | None = None,
    _: dict = Depends(require_admin),
) -> ProductListResponse:
    pool = get_db_pool()
    offset = (page - 1) * limit

    where_clauses: list[str] = []
    params: list = []
    idx = 1

    if category:
        where_clauses.append(f"c.slug = ${idx}")
        params.append(category)
        idx += 1
    if search:
        where_clauses.append(f"p.name ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_row = await pool.fetchrow(
        f"""
        SELECT COUNT(*) AS total FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        {where_sql}
        """,
        *params,
    )
    total = count_row["total"] if count_row else 0

    params += [limit, offset]
    rows = await pool.fetch(
        f"""
        SELECT p.id, p.name, p.energy_description, p.price, p.tag,
               p.img_url, p.cloudinary_public_id, p.stock, p.active,
               p.created_at, p.updated_at,
               c.slug AS category
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        {where_sql}
        ORDER BY p.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    return ProductListResponse(
        items=[_row_to_product(dict(r)) for r in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.post("/api/admin/products", response_model=ProductResponse, status_code=201)
async def create_product(body: ProductCreate, _: dict = Depends(require_admin)) -> ProductResponse:
    pool = get_db_pool()
    cat_row = await pool.fetchrow("SELECT id FROM categories WHERE slug = $1", body.category)
    if cat_row is None:
        cat_row = await pool.fetchrow(
            "INSERT INTO categories (slug, name) VALUES ($1, $2) RETURNING id",
            body.category,
            body.category.capitalize(),
        )
    category_id = cat_row["id"]

    row = await pool.fetchrow(
        """
        INSERT INTO products (category_id, name, energy_description, price, tag,
                              img_url, cloudinary_public_id, stock)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, name, energy_description, price, tag, img_url,
                  cloudinary_public_id, stock, active, created_at, updated_at
        """,
        category_id,
        body.name,
        body.description,
        body.price,
        body.tag,
        body.image_url,
        body.cloudinary_public_id,
        body.stock,
    )
    result = dict(row)
    result["category"] = body.category
    return _row_to_product(result)


@router.get("/api/admin/products/{product_id}", response_model=ProductResponse)
async def get_product_admin(product_id: int, _: dict = Depends(require_admin)) -> ProductResponse:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT p.id, p.name, p.energy_description, p.price, p.tag,
               p.img_url, p.cloudinary_public_id, p.stock, p.active,
               p.created_at, p.updated_at, c.slug AS category
        FROM products p LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.id = $1
        """,
        product_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return _row_to_product(dict(row))


@router.put("/api/admin/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    _: dict = Depends(require_admin),
) -> ProductResponse:
    pool = get_db_pool()
    existing = await pool.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    category_id = existing["category_id"]
    if body.category is not None:
        cat_row = await pool.fetchrow("SELECT id FROM categories WHERE slug = $1", body.category)
        if cat_row is None:
            cat_row = await pool.fetchrow(
                "INSERT INTO categories (slug, name) VALUES ($1, $2) RETURNING id",
                body.category,
                body.category.capitalize(),
            )
        category_id = cat_row["id"]

    row = await pool.fetchrow(
        """
        UPDATE products SET
            category_id = $1,
            name = COALESCE($2, name),
            energy_description = COALESCE($3, energy_description),
            price = COALESCE($4, price),
            tag = COALESCE($5, tag),
            img_url = COALESCE($6, img_url),
            cloudinary_public_id = COALESCE($7, cloudinary_public_id),
            stock = COALESCE($8, stock),
            active = COALESCE($9, active),
            updated_at = NOW()
        WHERE id = $10
        RETURNING id, name, energy_description, price, tag, img_url,
                  cloudinary_public_id, stock, active, created_at, updated_at
        """,
        category_id,
        body.name,
        body.description,
        body.price,
        body.tag,
        body.image_url,
        body.cloudinary_public_id,
        body.stock,
        body.active,
        product_id,
    )
    result = dict(row)
    result["category"] = body.category or ""
    return _row_to_product(result)


from fastapi.responses import Response

@router.delete("/api/admin/products/{product_id}")
async def delete_product(product_id: int, _: dict = Depends(require_admin)) -> Response:
    pool = get_db_pool()
    row = await pool.fetchrow(
        "SELECT cloudinary_public_id FROM products WHERE id = $1", product_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    public_id = row["cloudinary_public_id"]
    if public_id:
        _init_cloudinary()
        try:
            cloudinary.uploader.destroy(public_id)
        except Exception:
            pass  # No bloquear el borrado del producto si Cloudinary falla

    await pool.execute("DELETE FROM products WHERE id = $1", product_id)
    return Response(status_code=204)


@router.patch("/api/admin/products/{product_id}/stock", response_model=ProductResponse)
async def update_stock(
    product_id: int,
    stock: Annotated[int, Query(ge=0)],
    _: dict = Depends(require_admin),
) -> ProductResponse:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        UPDATE products SET stock = $1, updated_at = NOW()
        WHERE id = $2
        RETURNING id, name, energy_description, price, tag, img_url,
                  cloudinary_public_id, stock, active, created_at, updated_at,
                  category_id
        """,
        stock,
        product_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    result = dict(row)
    cat = await pool.fetchrow("SELECT slug FROM categories WHERE id = $1", result["category_id"])
    result["category"] = cat["slug"] if cat else ""
    return _row_to_product(result)
