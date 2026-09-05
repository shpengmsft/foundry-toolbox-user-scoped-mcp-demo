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
    fake_oauth_issuer: str = "http://localhost:8000"
    fake_oauth_audience: str = "user-scoped-mcp-demo"
    fake_oauth_client_id: str = "foundry-test-client"
    fake_oauth_redirect_uris: frozenset[str] = frozenset(
        {"http://localhost:8400/callback"}
    )
    fake_oauth_access_token_seconds: int = 900
    fake_oauth_refresh_token_seconds: int = 28800


def _csv_set(name: str, default: str = "") -> frozenset[str]:
    values = os.getenv(name, default).split(",")
    return frozenset(value.strip() for value in values if value.strip())


@lru_cache
def get_settings() -> Settings:
    auth_mode = os.getenv("AUTH_MODE", "demo").lower()
    if auth_mode not in {"demo", "entra", "entra_passthrough", "fake_oauth"}:
        raise ValueError(
            "AUTH_MODE must be 'demo', 'entra', 'entra_passthrough', or 'fake_oauth'"
        )

    tenant_id = os.getenv("ENTRA_TENANT_ID")
    audience = os.getenv("ENTRA_AUDIENCE")
    if auth_mode in {"entra", "entra_passthrough"} and not tenant_id:
        raise ValueError("ENTRA_TENANT_ID is required for Entra authentication")
    if auth_mode == "entra" and not audience:
        raise ValueError("ENTRA_TENANT_ID and ENTRA_AUDIENCE are required in entra mode")

    default_engineers = ""
    default_finance = ""
    default_admins = ""
    if auth_mode == "fake_oauth":
        default_engineers = "11111111-1111-1111-1111-111111111111"
        default_finance = "22222222-2222-2222-2222-222222222222"
        default_admins = "33333333-3333-3333-3333-333333333333"

    return Settings(
        auth_mode=auth_mode,
        tenant_id=tenant_id,
        audience=audience,
        required_scope=os.getenv("ENTRA_REQUIRED_SCOPE", "mcp.access"),
        engineering_user_ids=_csv_set("ENGINEERING_USER_IDS", default_engineers),
        finance_user_ids=_csv_set("FINANCE_USER_IDS", default_finance),
        admin_user_ids=_csv_set("ADMIN_USER_IDS", default_admins),
        allowed_origins=_csv_set(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ),
        server_host=os.getenv("SERVER_HOST", "127.0.0.1"),
        fake_oauth_issuer=os.getenv(
            "FAKE_OAUTH_ISSUER",
            "http://localhost:8000",
        ).rstrip("/"),
        fake_oauth_audience=os.getenv(
            "FAKE_OAUTH_AUDIENCE",
            "user-scoped-mcp-demo",
        ),
        fake_oauth_client_id=os.getenv(
            "FAKE_OAUTH_CLIENT_ID",
            "foundry-test-client",
        ),
        fake_oauth_redirect_uris=_csv_set(
            "FAKE_OAUTH_REDIRECT_URIS",
            "http://localhost:8400/callback",
        ),
        fake_oauth_access_token_seconds=int(
            os.getenv("FAKE_OAUTH_ACCESS_TOKEN_SECONDS", "900")
        ),
        fake_oauth_refresh_token_seconds=int(
            os.getenv("FAKE_OAUTH_REFRESH_TOKEN_SECONDS", "28800")
        ),
    )
