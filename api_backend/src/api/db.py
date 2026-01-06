from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.api.core.settings import get_settings

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "Database is not configured. Set BACKEND_DATABASE_URL (preferred) or POSTGRES_URL."
        )
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = _build_engine()
        _sessionmaker = async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker


# PUBLIC_INTERFACE
@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession and ensure cleanup."""
    maker = _get_sessionmaker()
    async with maker() as session:
        yield session


# PUBLIC_INTERFACE
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession."""
    async with session_scope() as session:
        yield session
