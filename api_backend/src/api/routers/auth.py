from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.security import create_access_token, hash_password, verify_password
from src.api.db import get_db_session
from src.api.deps import AuthUser, get_current_user
from src.api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

ALLOWED_ROLES = {"customer", "restaurant", "delivery", "admin"}


@router.post(
    "/register",
    response_model=UserOut,
    summary="Register a new user",
    description="Create a new user account. Role defaults to 'customer'.",
)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_db_session)) -> UserOut:
    """Register a new user."""
    if payload.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    pw_hash = hash_password(payload.password)

    try:
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO users (email, password_hash, full_name, role, phone)
                    VALUES (:email, :password_hash, :full_name, :role, :phone)
                    RETURNING id, email, full_name, role, phone, is_active, created_at
                    """
                ),
                {
                    "email": payload.email,
                    "password_hash": pw_hash,
                    "full_name": payload.full_name,
                    "role": payload.role,
                    "phone": payload.phone,
                },
            )
        ).mappings().first()
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    return UserOut(**row)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and obtain JWT",
    description="Validate credentials and return a bearer token.",
)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Login with email/password and receive a JWT."""
    user = (
        await session.execute(
            text(
                """
                SELECT id, email, password_hash, role, is_active
                FROM users
                WHERE email = :email
                """
            ),
            {"email": payload.email},
        )
    ).mappings().first()

    if not user or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=str(user["id"]), role=user["role"])
    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Get current user",
    description="Return the authenticated user's profile.",
)
async def me(user: AuthUser = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)) -> UserOut:
    """Return current user profile."""
    row = (
        await session.execute(
            text(
                """
                SELECT id, email, full_name, role, phone, is_active, created_at
                FROM users
                WHERE id = :id
                """
            ),
            {"id": str(user.id)},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**row)
