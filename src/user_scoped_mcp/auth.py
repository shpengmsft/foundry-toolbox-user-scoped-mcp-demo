from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request, status

from .config import Settings


@dataclass(frozen=True)
class Actor:
    object_id: str
    display_name: str
    roles: frozenset[str]
    claims: dict[str, Any]


DEMO_ACTORS = {
    "demo-engineer": Actor(
        object_id="11111111-1111-1111-1111-111111111111",
        display_name="Demo Engineer",
        roles=frozenset({"Engineering"}),
        claims={"auth_mode": "demo"},
    ),
    "demo-finance": Actor(
        object_id="22222222-2222-2222-2222-222222222222",
        display_name="Demo Finance User",
        roles=frozenset({"Finance"}),
        claims={"auth_mode": "demo"},
    ),
    "demo-admin": Actor(
        object_id="33333333-3333-3333-3333-333333333333",
        display_name="Demo Administrator",
        roles=frozenset({"Engineering", "Finance", "Demo.Admin"}),
        claims={"auth_mode": "demo"},
    ),
}


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _actor_from_demo_token(token: str) -> Actor:
    actor = DEMO_ACTORS.get(token)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown demo token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return actor


def _actor_from_entra_token(token: str, settings: Settings) -> Actor:
    assert settings.tenant_id is not None

    allowed_issuers = {
        f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0",
        f"https://sts.windows.net/{settings.tenant_id}/",
    }
    jwks_uri = f"https://login.microsoftonline.com/{settings.tenant_id}/discovery/v2.0/keys"

    try:
        unverified_claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False},
        )
        issuer = str(unverified_claims.get("iss", ""))
        if issuer not in allowed_issuers:
            raise jwt.InvalidIssuerError("Token issuer is not allowed")
        if str(unverified_claims.get("tid", "")) != settings.tenant_id:
            raise jwt.InvalidIssuerError("Token tenant is not allowed")

        signing_key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(token)
        decode_options = {"require": ["exp", "iat", "iss", "aud", "oid", "tid"]}
        if settings.auth_mode == "entra_passthrough" and settings.audience is None:
            decode_options["verify_aud"] = False

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=issuer,
            options=decode_options,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The Entra access token is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    scopes = frozenset(str(claims.get("scp", "")).split())
    if settings.auth_mode == "entra" and settings.required_scope not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing delegated scope: {settings.required_scope}",
        )

    object_id = str(claims["oid"])
    roles: set[str] = set()
    if object_id in settings.engineering_user_ids:
        roles.add("Engineering")
    if object_id in settings.finance_user_ids:
        roles.add("Finance")
    if object_id in settings.admin_user_ids:
        roles.update({"Engineering", "Finance", "Demo.Admin"})

    return Actor(
        object_id=object_id,
        display_name=str(
            claims.get("name")
            or claims.get("preferred_username")
            or claims["oid"]
        ),
        roles=frozenset(roles),
        claims=claims,
    )


def authenticate(request: Request, settings: Settings) -> Actor:
    token = _bearer_token(request)
    if settings.auth_mode == "demo":
        return _actor_from_demo_token(token)
    return _actor_from_entra_token(token, settings)
