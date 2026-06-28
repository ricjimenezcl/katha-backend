from __future__ import annotations
"""Router de talleres: CRUD admin + listado público."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth_utils import require_admin
from ..db import get_db_pool
from ..schemas import TallerCreate, TallerResponse, TallerUpdate

router = APIRouter(tags=["talleres"])


def _row_to_taller(row: dict) -> TallerResponse:
    return TallerResponse(
        id=row["id"],
        titulo=row["titulo"],
        descripcion=row["descripcion"],
        horas=row["horas"],
        nivel=row["nivel"],
        detalle=row["detalle"],
        icono=row["icono"] or "",
        sort_order=row["sort_order"],
        active=row["active"],
    )


# ── Público ───────────────────────────────────────────────────────────────────

@router.get("/api/talleres", response_model=list[TallerResponse])
async def list_talleres_public() -> list[TallerResponse]:
    pool = get_db_pool()
    rows = await pool.fetch(
        "SELECT id, titulo, descripcion, horas, nivel, detalle, icono, sort_order, active "
        "FROM talleres WHERE active = TRUE ORDER BY sort_order"
    )
    return [_row_to_taller(dict(r)) for r in rows]


# ── Admin ──────────────────────────────────────────────────────────────────────

@router.get("/api/admin/talleres", response_model=list[TallerResponse])
async def list_talleres_admin(_: dict = Depends(require_admin)) -> list[TallerResponse]:
    pool = get_db_pool()
    rows = await pool.fetch(
        "SELECT id, titulo, descripcion, horas, nivel, detalle, icono, sort_order, active "
        "FROM talleres ORDER BY sort_order"
    )
    return [_row_to_taller(dict(r)) for r in rows]


@router.post("/api/admin/talleres", response_model=TallerResponse, status_code=status.HTTP_201_CREATED)
async def create_taller(body: TallerCreate, _: dict = Depends(require_admin)) -> TallerResponse:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO talleres (titulo, descripcion, horas, nivel, detalle, icono, sort_order, active)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, titulo, descripcion, horas, nivel, detalle, icono, sort_order, active
        """,
        body.titulo, body.descripcion, body.horas, body.nivel,
        body.detalle, body.icono, body.sort_order, body.active,
    )
    return _row_to_taller(dict(row))


@router.put("/api/admin/talleres/{taller_id}", response_model=TallerResponse)
async def update_taller(
    taller_id: int, body: TallerUpdate, _: dict = Depends(require_admin)
) -> TallerResponse:
    pool = get_db_pool()
    existing = await pool.fetchrow("SELECT * FROM talleres WHERE id = $1", taller_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taller no encontrado")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return _row_to_taller(dict(existing))

    set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(updates))
    values = list(updates.values())
    row = await pool.fetchrow(
        f"""
        UPDATE talleres SET {set_clause}, updated_at = NOW()
        WHERE id = $1
        RETURNING id, titulo, descripcion, horas, nivel, detalle, icono, sort_order, active
        """,
        taller_id, *values,
    )
    return _row_to_taller(dict(row))


@router.delete("/api/admin/talleres/{taller_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_taller(taller_id: int, _: dict = Depends(require_admin)) -> None:
    pool = get_db_pool()
    result = await pool.execute("DELETE FROM talleres WHERE id = $1", taller_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taller no encontrado")
