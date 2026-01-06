import os
from dataclasses import dataclass
from typing import List


def _split_csv(value: str) -> List[str]:
    parts = [p.strip() for p in (value or "").split(",")]
    return [p for p in parts if p]


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
      - BACKEND_DATABASE_URL (preferred) OR POSTGRES_URL
      - BACKEND_JWT_SECRET, BACKEND_JWT_ALGORITHM, BACKEND_JWT_EXPIRES_MINUTES
      - BACKEND_CORS_ORIGINS (comma-separated or '*')
      - BACKEND_ENABLE_DEV_ADMIN ('true'/'false')
    """
    db_url = os.getenv("BACKEND_DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    jwt_secret = os.getenv("BACKEND_JWT_SECRET", "")
    jwt_algorithm = os.getenv("BACKEND_JWT_ALGORITHM", "HS256")
    jwt_expires = int(os.getenv("BACKEND_JWT_EXPIRES_MINUTES", "10080"))
    cors_raw = os.getenv("BACKEND_CORS_ORIGINS", "*")
    enable_dev_admin = os.getenv("BACKEND_ENABLE_DEV_ADMIN", "false").lower() in ("1", "true", "yes")

    # In development templates, allow running without DB URL until first DB call.
    # Routes that use DB will still fail with a clear error.
    cors = ["*"] if cors_raw.strip() == "*" else _split_csv(cors_raw)

    return Settings(
        database_url=db_url,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        jwt_expires_minutes=jwt_expires,
        cors_origins=cors,
        enable_dev_admin=enable_dev_admin,
    )
