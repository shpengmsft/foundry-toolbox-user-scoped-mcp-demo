import base64
import hashlib
import html
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jwt.algorithms import RSAAlgorithm

from .config import Settings


@dataclass(frozen=True)
class FakeIdentity:
    object_id: str
    display_name: str
    username: str


@dataclass(frozen=True)
class AuthorizationCode:
    client_id: str
    redirect_uri: str
    scope: str
    identity_key: str
    code_challenge: str | None
    code_challenge_method: str | None
    expires_at: int


FAKE_IDENTITIES = {
    "engineer": FakeIdentity(
        object_id="11111111-1111-1111-1111-111111111111",
        display_name="Demo Engineer",
        username="engineer@example.test",
    ),
    "finance": FakeIdentity(
        object_id="22222222-2222-2222-2222-222222222222",
        display_name="Demo Finance User",
        username="finance@example.test",
    ),
    "admin": FakeIdentity(
        object_id="33333333-3333-3333-3333-333333333333",
        display_name="Demo Administrator",
        username="admin@example.test",
    ),
}


class FakeOAuthProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public_key = self._private_key.public_key()
        self._key_id = secrets.token_hex(8)
        self._codes: dict[str, AuthorizationCode] = {}
        self._lock = threading.Lock()

    def discovery_document(self) -> dict[str, Any]:
        issuer = self.settings.fake_oauth_issuer
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "jwks_uri": f"{issuer}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256", "plain"],
            "scopes_supported": ["mcp.access", "offline_access"],
        }

    def jwks_document(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self._public_key))
        jwk.update({"kid": self._key_id, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def authorize(
        self,
        *,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        scope: str,
        state: str | None,
        identity_key: str | None,
        code_challenge: str | None,
        code_challenge_method: str | None,
    ) -> HTMLResponse | RedirectResponse:
        self._validate_authorization_request(
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        if identity_key is None:
            return HTMLResponse(
                self._identity_picker(
                    response_type=response_type,
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    scope=scope,
                    state=state,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                )
            )

        if identity_key not in FAKE_IDENTITIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown test_user",
            )

        code = secrets.token_urlsafe(32)
        with self._lock:
            self._remove_expired_codes()
            self._codes[code] = AuthorizationCode(
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=self._normalize_scope(scope),
                identity_key=identity_key,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                expires_at=int(time.time()) + 300,
            )

        query = {"code": code}
        if state is not None:
            query["state"] = state
        separator = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{separator}{urlencode(query)}", status_code=302)

    def exchange_token(self, form: dict[str, str]) -> dict[str, Any]:
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return self._exchange_authorization_code(form)
        if grant_type == "refresh_token":
            return self._exchange_refresh_token(form)
        raise self._oauth_error("unsupported_grant_type", "Unsupported grant_type")

    def verify_access_token(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience=self.settings.fake_oauth_audience,
                issuer=self.settings.fake_oauth_issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub", "oid", "token_use"]
                },
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The fake OAuth access token is invalid",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    def _validate_authorization_request(
        self,
        *,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        scope: str,
        code_challenge: str | None,
        code_challenge_method: str | None,
    ) -> None:
        if response_type != "code":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only response_type=code is supported",
            )
        if client_id != self.settings.fake_oauth_client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown client_id",
            )
        if redirect_uri not in self.settings.fake_oauth_redirect_uris:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect_uri is not allowed",
            )
        if self.settings.required_scope not in scope.split():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Required scope is missing: {self.settings.required_scope}",
            )
        if code_challenge_method not in {None, "plain", "S256"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported code_challenge_method",
            )
        if code_challenge_method is not None and not code_challenge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="code_challenge is required when code_challenge_method is supplied",
            )

    def _exchange_authorization_code(self, form: dict[str, str]) -> dict[str, Any]:
        code = form.get("code", "")
        with self._lock:
            authorization = self._codes.pop(code, None)
            self._remove_expired_codes()

        if authorization is None or authorization.expires_at < int(time.time()):
            raise self._oauth_error("invalid_grant", "Authorization code is invalid or expired")
        if form.get("client_id") != authorization.client_id:
            raise self._oauth_error("invalid_client", "client_id does not match")
        if form.get("redirect_uri") != authorization.redirect_uri:
            raise self._oauth_error("invalid_grant", "redirect_uri does not match")
        if not self._valid_code_verifier(
            form.get("code_verifier"),
            authorization.code_challenge,
            authorization.code_challenge_method,
        ):
            raise self._oauth_error("invalid_grant", "PKCE code_verifier does not match")

        return self._token_response(
            identity_key=authorization.identity_key,
            scope=authorization.scope,
        )

    def _exchange_refresh_token(self, form: dict[str, str]) -> dict[str, Any]:
        if form.get("client_id") != self.settings.fake_oauth_client_id:
            raise self._oauth_error("invalid_client", "Unknown client_id")
        try:
            claims = jwt.decode(
                form.get("refresh_token", ""),
                self._public_key,
                algorithms=["RS256"],
                audience=self.settings.fake_oauth_client_id,
                issuer=self.settings.fake_oauth_issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "token_use"]},
            )
        except jwt.PyJWTError as exc:
            raise self._oauth_error("invalid_grant", "Refresh token is invalid or expired") from exc
        if claims.get("token_use") != "refresh":
            raise self._oauth_error("invalid_grant", "Token is not a refresh token")
        identity_key = str(claims["sub"])
        if identity_key not in FAKE_IDENTITIES:
            raise self._oauth_error("invalid_grant", "Refresh token identity is invalid")
        return self._token_response(
            identity_key=identity_key,
            scope=str(claims.get("scope", "mcp.access offline_access")),
        )

    def _token_response(self, *, identity_key: str, scope: str) -> dict[str, Any]:
        now = int(time.time())
        identity = FAKE_IDENTITIES[identity_key]
        normalized_scope = self._normalize_scope(scope)
        access_token = jwt.encode(
            {
                "iss": self.settings.fake_oauth_issuer,
                "aud": self.settings.fake_oauth_audience,
                "sub": identity.object_id,
                "oid": identity.object_id,
                "name": identity.display_name,
                "preferred_username": identity.username,
                "scp": normalized_scope,
                "token_use": "access",
                "iat": now,
                "exp": now + self.settings.fake_oauth_access_token_seconds,
                "jti": secrets.token_hex(16),
            },
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._key_id},
        )
        refresh_token = jwt.encode(
            {
                "iss": self.settings.fake_oauth_issuer,
                "aud": self.settings.fake_oauth_client_id,
                "sub": identity_key,
                "scope": normalized_scope,
                "token_use": "refresh",
                "iat": now,
                "exp": now + self.settings.fake_oauth_refresh_token_seconds,
                "jti": secrets.token_hex(16),
            },
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._key_id},
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self.settings.fake_oauth_access_token_seconds,
            "refresh_token": refresh_token,
            "scope": normalized_scope,
        }

    def _identity_picker(
        self,
        *,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        scope: str,
        state: str | None,
        code_challenge: str | None,
        code_challenge_method: str | None,
    ) -> str:
        base_params = {
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        if state is not None:
            base_params["state"] = state
        if code_challenge is not None:
            base_params["code_challenge"] = code_challenge
        if code_challenge_method is not None:
            base_params["code_challenge_method"] = code_challenge_method

        links = []
        for identity_key, identity in FAKE_IDENTITIES.items():
            params = {**base_params, "test_user": identity_key}
            href = f"/oauth/authorize?{urlencode(params)}"
            links.append(
                f'<li><a href="{html.escape(href, quote=True)}">'
                f"{html.escape(identity.display_name)}</a></li>"
            )

        return (
            "<!doctype html><html><head><title>Fake OAuth sign-in</title></head>"
            "<body><h1>Fake OAuth sign-in</h1>"
            "<p>Test-only provider. Select the identity for this authorization.</p>"
            f"<ul>{''.join(links)}</ul></body></html>"
        )

    def _remove_expired_codes(self) -> None:
        now = int(time.time())
        expired = [code for code, value in self._codes.items() if value.expires_at < now]
        for code in expired:
            self._codes.pop(code, None)

    @staticmethod
    def _normalize_scope(scope: str) -> str:
        return " ".join(dict.fromkeys(scope.split()))

    @staticmethod
    def _valid_code_verifier(
        verifier: str | None,
        challenge: str | None,
        method: str | None,
    ) -> bool:
        if challenge is None:
            return True
        if verifier is None:
            return False
        if re.fullmatch(r"[A-Za-z0-9\-._~]{43,128}", verifier) is None:
            return False
        if method in {None, "plain"}:
            return secrets.compare_digest(verifier, challenge)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return secrets.compare_digest(encoded, challenge)

    @staticmethod
    def _oauth_error(error: str, description: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": error, "error_description": description},
        )


@lru_cache
def get_fake_oauth_provider(settings: Settings) -> FakeOAuthProvider:
    return FakeOAuthProvider(settings)
