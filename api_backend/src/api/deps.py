from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.security import decode_access_token
from src.api.db import get_db_session

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool


async def _load_user(session: AsyncSession, user_id: str) -> Optional[AuthUser]:
    row = (
        await session.execute(
            text(
                """
                SELECT id, email, full_name, role, is_active
                FROM users
                WHERE id = :id
                """
            ),
            {"id": user_id},
        )
    ).mappings().first()
    if not row:
        return None
    return AuthUser(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        is_active=row["is_active"],
    )


# PUBLIC_INTERFACE
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> AuthUser:
    """Resolve the current authenticated user from the Authorization: Bearer token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = await _load_user(session, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or not found")

    return user


# PUBLIC_INTERFACE
def require_roles(*allowed: str):
    """Dependency factory to enforce user roles."""

    async def _checker(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _checker


# PUBLIC_INTERFACE
def role_in(user: AuthUser, allowed: Iterable[str]) -> bool:
    """Utility to test if a user is in an allowed role set."""
    return user.role in set(allowed)
