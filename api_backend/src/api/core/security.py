from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import jwt
from passlib.context import CryptContext

from src.api.core.settings import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# PUBLIC_INTERFACE
def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


# PUBLIC_INTERFACE
def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plain-text password against a stored hash."""
    return pwd_context.verify(plain_password, password_hash)


# PUBLIC_INTERFACE
def create_access_token(subject: str, role: str, expires_minutes: Optional[int] = None) -> str:
    """Create a JWT access token.

    Args:
        subject: User ID (UUID string).
        role: One of 'customer', 'restaurant', 'delivery', 'admin'.
        expires_minutes: Override token TTL.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("JWT is not configured. Set BACKEND_JWT_SECRET.")
    ttl = expires_minutes if expires_minutes is not None else settings.jwt_expires_minutes
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# PUBLIC_INTERFACE
def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token.

    Raises:
        JWTError if invalid/expired.
    """
    settings = get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("JWT is not configured. Set BACKEND_JWT_SECRET.")
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
