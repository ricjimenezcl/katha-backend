from __future__ import annotations
"""Router de autenticación: login y perfil del usuario actual."""
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth_utils import create_access_token, get_current_user, hash_password, verify_password
from ..db import get_db_pool
from ..schemas import LoginRequest, TokenResponse, UserMe

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    pool = get_db_pool()
    row = await pool.fetchrow(
        "SELECT id, email, display_name, role, password_hash FROM users WHERE email = $1",
        body.email.strip().lower(),
    )
    if row is None or not row["password_hash"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    if not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

    token = create_access_token(
        {"sub": str(row["id"]), "email": row["email"], "role": row["role"]}
    )
    return TokenResponse(
        access_token=token,
        user={"id": row["id"], "email": row["email"], "display_name": row["display_name"], "role": row["role"]},
    )


@router.get("/me", response_model=UserMe)
async def me(current_user: dict = Depends(get_current_user)) -> UserMe:
    pool = get_db_pool()
    row = await pool.fetchrow(
        "SELECT id, email, display_name, role FROM users WHERE id = $1",
        int(current_user["sub"]),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return UserMe(**dict(row))


@router.post("/register-admin")
async def register_admin(body: LoginRequest, current_user: dict = Depends(get_current_user)) -> dict:
    """Solo un admin puede crear otro admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores pueden registrar otros admins")

    pool = get_db_pool()
    hashed = hash_password(body.password)
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO users (email, display_name, role, password_hash)
            VALUES ($1, $1, 'admin', $2)
            ON CONFLICT (email) DO UPDATE SET password_hash = $2, role = 'admin'
            RETURNING id, email, role
            """,
            body.email.strip().lower(),
            hashed,
        )
        return {"id": row["id"], "email": row["email"], "role": row["role"]}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
