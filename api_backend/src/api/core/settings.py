import os
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote_plus


def _split_csv(value: str) -> List[str]:
    parts = [p.strip() for p in (value or "").split(",")]
    return [p for p in parts if p]


def _truthy(value: Optional[str]) -> bool:
    return (value or "").lower() in ("1", "true", "yes", "y", "on")


def _build_postgres_async_url_from_parts() -> str:
    """
    Build an async SQLAlchemy Postgres URL from either POSTGRES_* or DB_* variables.
    Returns empty string if insufficient values are present.

    Supported env var sets (either is fine):
      - POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT, POSTGRES_HOST
      - DB_USER, DB_PASSWORD, DB_NAME, DB_PORT, DB_HOST
    """
    user = os.getenv("POSTGRES_USER") or os.getenv("DB_USER") or ""
    password = os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD") or ""
    db = os.getenv("POSTGRES_DB") or os.getenv("DB_NAME") or ""
    port = os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT") or ""
    host = os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST") or ""

    if not (user and password and db and port and host):
        return ""

    # Quote user/pass defensively; database/host/port are generally safe as-is.
    user_q = quote_plus(user)
    pw_q = quote_plus(password)
    return f"postgresql+asyncpg://{user_q}:{pw_q}@{host}:{port}/{db}"


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_expires_minutes: int
    cors_origins: List[str]
    enable_dev_admin: bool


# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """Load application settings from environment variables.

    Environment variables:
      - BACKEND_DATABASE_URL (preferred): postgresql+asyncpg://user:pass@host:port/dbname
      - POSTGRES_URL (alternative, injected by database container in this workspace)
      - OR individual parts:
          POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
        (or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD)

      - BACKEND_JWT_SECRET, BACKEND_JWT_ALGORITHM, BACKEND_JWT_EXPIRES_MINUTES
      - BACKEND_CORS_ORIGINS (comma-separated or '*')
      - BACKEND_ENABLE_DEV_ADMIN ('true'/'false')
    """
    # Prefer explicit backend URL; otherwise try POSTGRES_URL; otherwise compose from parts.
    db_url = (
        os.getenv("BACKEND_DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or _build_postgres_async_url_from_parts()
        or ""
    )

    jwt_secret = os.getenv("BACKEND_JWT_SECRET", "")
    jwt_algorithm = os.getenv("BACKEND_JWT_ALGORITHM", "HS256")
    jwt_expires = int(os.getenv("BACKEND_JWT_EXPIRES_MINUTES", "10080"))

    cors_raw = os.getenv("BACKEND_CORS_ORIGINS", "*").strip()
    enable_dev_admin = _truthy(os.getenv("BACKEND_ENABLE_DEV_ADMIN", "false"))

    # Always allow local preview frontend by default; additionally allow configured origins.
    # If '*' is used, keep it as the only value (FastAPI CORSMiddleware treats it specially).
    if cors_raw == "*":
        cors = ["*"]
    else:
        cors = sorted(set(["http://localhost:3000", *(_split_csv(cors_raw))]))

    return Settings(
        database_url=db_url,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        jwt_expires_minutes=jwt_expires,
        cors_origins=cors,
        enable_dev_admin=enable_dev_admin,
    )
