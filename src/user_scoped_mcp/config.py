import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    auth_mode: str
    tenant_id: str | None
    audience: str | None
    required_scope: str
    engineering_user_ids: frozenset[str]
    finance_user_ids: frozenset[str]
    admin_user_ids: frozenset[str]
    allowed_origins: frozenset[str]
    server_host: str


def _csv_set(name: str, default: str = "") -> frozenset[str]:
    values = os.getenv(name, default).split(",")
    return frozenset(value.strip() for value in values if value.strip())


@lru_cache
def get_settings() -> Settings:
    auth_mode = os.getenv("AUTH_MODE", "demo").lower()
    if auth_mode not in {"demo", "entra", "entra_passthrough"}:
        raise ValueError(
            "AUTH_MODE must be 'demo', 'entra', or 'entra_passthrough'"
        )

    tenant_id = os.getenv("ENTRA_TENANT_ID")
    audience = os.getenv("ENTRA_AUDIENCE")
    if auth_mode in {"entra", "entra_passthrough"} and not tenant_id:
        raise ValueError("ENTRA_TENANT_ID is required for Entra authentication")
    if auth_mode == "entra" and not audience:
        raise ValueError("ENTRA_TENANT_ID and ENTRA_AUDIENCE are required in entra mode")

    return Settings(
        auth_mode=auth_mode,
        tenant_id=tenant_id,
        audience=audience,
        required_scope=os.getenv("ENTRA_REQUIRED_SCOPE", "mcp.access"),
        engineering_user_ids=_csv_set("ENGINEERING_USER_IDS"),
        finance_user_ids=_csv_set("FINANCE_USER_IDS"),
        admin_user_ids=_csv_set("ADMIN_USER_IDS"),
        allowed_origins=_csv_set(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ),
        server_host=os.getenv("SERVER_HOST", "127.0.0.1"),
    )
