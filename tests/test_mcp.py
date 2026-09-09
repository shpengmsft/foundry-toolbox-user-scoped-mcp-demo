import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi.testclient import TestClient

from user_scoped_mcp import auth
from user_scoped_mcp.app import app
from user_scoped_mcp.auth import Actor, _actor_from_entra_token
from user_scoped_mcp.config import Settings, get_settings
from user_scoped_mcp.oauth_provider import get_fake_oauth_provider
from user_scoped_mcp.tools import call_tool

client = TestClient(app)


def request(method: str, token: str, params: dict | None = None):
    return client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def tool_names(token: str) -> set[str]:
    response = request("tools/list", token)
    assert response.status_code == 200
    return {tool["name"] for tool in response.json()["result"]["tools"]}


def test_engineer_and_finance_receive_different_manifests():
    engineer = tool_names("demo-engineer")
    finance = tool_names("demo-finance")

    assert engineer == {
        "get_current_user",
        "search_service_incidents",
        "get_deployment_status",
        "create_incident_mitigation_plan",
    }
    assert finance == {
        "get_current_user",
        "search_budget_variances",
        "get_cost_center_status",
        "create_spend_mitigation_plan",
    }


def test_initialize_requests_concise_grounded_output():
    response = request("initialize", "demo-engineer")
    instructions = response.json()["result"]["instructions"]

    assert "no more than three bullets" in instructions
    assert "only when the user explicitly requests a plan" in instructions
    assert "Do not add recommendations" in instructions
    assert "lower severity number means higher priority" in instructions


def test_admin_receives_all_tools():
    assert tool_names("demo-admin") == {
        "get_current_user",
        "search_service_incidents",
        "get_deployment_status",
        "create_incident_mitigation_plan",
        "search_budget_variances",
        "get_cost_center_status",
        "create_spend_mitigation_plan",
    }


def test_call_reauthorizes_hidden_tool():
    response = request(
        "tools/call",
        "demo-finance",
        {"name": "get_deployment_status", "arguments": {"service": "checkout-api"}},
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32003


def test_unknown_demo_token_is_rejected():
    response = request("tools/list", "not-a-user")
    assert response.status_code == 401


def test_current_user_reports_unassigned_for_unknown_role():
    actor = Actor(
        object_id="unmapped-oid",
        display_name="Unmapped User",
        roles=frozenset(),
        claims={},
    )
    result = call_tool(actor, "get_current_user", {})
    assert result["structuredContent"]["role"] == "Unassigned"


def test_engineering_workflow_uses_deterministic_inputs():
    search = request(
        "tools/call",
        "demo-engineer",
        {"name": "search_service_incidents", "arguments": {"query": "checkout"}},
    ).json()["result"]["structuredContent"]
    assert [item["id"] for item in search["incidents"]] == ["ENG-1042"]

    plan = request(
        "tools/call",
        "demo-engineer",
        {
            "name": "create_incident_mitigation_plan",
            "arguments": {"incident_id": "ENG-1042"},
        },
    ).json()["result"]["structuredContent"]
    assert plan["found"] is True
    assert len(plan["plan"]) == 3


def test_finance_workflow_uses_deterministic_inputs():
    search = request(
        "tools/call",
        "demo-finance",
        {"name": "search_budget_variances", "arguments": {"query": "cloud"}},
    ).json()["result"]["structuredContent"]
    assert [item["id"] for item in search["variances"]] == ["FIN-2041"]

    plan = request(
        "tools/call",
        "demo-finance",
        {
            "name": "create_spend_mitigation_plan",
            "arguments": {"variance_id": "FIN-2041"},
        },
    ).json()["result"]["structuredContent"]
    assert plan["found"] is True
    assert len(plan["plan"]) == 3


def test_broad_risk_query_returns_current_engineering_records():
    search = request(
        "tools/call",
        "demo-engineer",
        {
            "name": "search_service_incidents",
            "arguments": {"query": "largest current risk for my team"},
        },
    ).json()["result"]["structuredContent"]

    assert [item["id"] for item in search["incidents"]] == ["ENG-1042", "ENG-1048"]
    assert search["severityConvention"] == "Lower number means higher severity."


def test_github_user_id_drives_manifest_and_ignores_scopes(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"id": 83468449, "login": "shpengmsft"}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 10.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers):
            assert url == "https://api.github.com/user"
            assert headers["Authorization"] == "Bearer opaque-github-token"
            return FakeResponse()

    monkeypatch.setenv("AUTH_MODE", "github")
    monkeypatch.setenv("ENGINEERING_USER_IDS", "83468449")
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)
    get_settings.cache_clear()
    try:
        assert tool_names("opaque-github-token") == {
            "get_current_user",
            "search_service_incidents",
            "get_deployment_status",
            "create_incident_mitigation_plan",
        }
    finally:
        get_settings.cache_clear()


def test_unmapped_github_user_receives_default_finance_manifest(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"id": 99999999, "login": "second-user"}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers):
            return FakeResponse()

    monkeypatch.setenv("AUTH_MODE", "github")
    monkeypatch.setenv("ENGINEERING_USER_IDS", "83468449")
    monkeypatch.setenv("GITHUB_DEFAULT_ROLE", "finance")
    monkeypatch.delenv("FINANCE_USER_IDS", raising=False)
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)
    get_settings.cache_clear()
    try:
        assert tool_names("second-opaque-github-token") == {
            "get_current_user",
            "search_budget_variances",
            "get_cost_center_status",
            "create_spend_mitigation_plan",
        }
    finally:
        get_settings.cache_clear()


def test_health_is_anonymous():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_untrusted_browser_origin_is_rejected():
    response = client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer demo-engineer",
            "Origin": "https://untrusted.example",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 403


def test_non_object_json_rpc_request_is_rejected():
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer demo-engineer"},
        json=[],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


def test_entra_passthrough_maps_oid_without_dedicated_scope(monkeypatch):
    settings = Settings(
        auth_mode="entra_passthrough",
        tenant_id="tenant-id",
        audience=None,
        required_scope="mcp.access",
        engineering_user_ids=frozenset({"engineer-oid"}),
        finance_user_ids=frozenset(),
        admin_user_ids=frozenset(),
        allowed_origins=frozenset(),
        server_host="127.0.0.1",
    )

    class FakeJwkClient:
        def __init__(self, _: str):
            pass

        def get_signing_key_from_jwt(self, _: str):
            return SimpleNamespace(key="test-key")

    def fake_decode(*args, **kwargs):
        if kwargs.get("options", {}).get("verify_signature") is False:
            return {
                "iss": "https://login.microsoftonline.com/tenant-id/v2.0",
                "tid": "tenant-id",
            }
        assert kwargs["audience"] is None
        assert kwargs["options"]["verify_aud"] is False
        return {
            "oid": "engineer-oid",
            "name": "Engineer",
            "aud": "existing-foundry-audience",
            "tid": "tenant-id",
            "roles": ["Finance"],
        }

    monkeypatch.setattr(jwt, "PyJWKClient", FakeJwkClient)
    monkeypatch.setattr(jwt, "decode", fake_decode)

    actor = _actor_from_entra_token("signed-jwt", settings)
    assert actor.object_id == "engineer-oid"
    assert actor.roles == frozenset({"Engineering"})


@pytest.fixture
def fake_oauth(monkeypatch):
    values = {
        "AUTH_MODE": "fake_oauth",
        "FAKE_OAUTH_ISSUER": "http://testserver",
        "FAKE_OAUTH_AUDIENCE": "test-mcp-audience",
        "FAKE_OAUTH_CLIENT_ID": "test-public-client",
        "FAKE_OAUTH_REDIRECT_URIS": "https://foundry.example/callback",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    get_fake_oauth_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_fake_oauth_provider.cache_clear()


def authorize_test_user(identity: str, *, verifier: str | None = None) -> str:
    params = {
        "response_type": "code",
        "client_id": "test-public-client",
        "redirect_uri": "https://foundry.example/callback",
        "scope": "mcp.access offline_access",
        "state": "state-123",
        "test_user": identity,
    }
    if verifier is not None:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        params["code_challenge"] = (
            base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )
        params["code_challenge_method"] = "S256"

    response = client.get("/oauth/authorize", params=params, follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["state"] == ["state-123"]
    return query["code"][0]


def exchange_code(code: str, *, verifier: str | None = None) -> dict:
    form = {
        "grant_type": "authorization_code",
        "client_id": "test-public-client",
        "redirect_uri": "https://foundry.example/callback",
        "code": code,
    }
    if verifier is not None:
        form["code_verifier"] = verifier
    response = client.post("/oauth/token", data=form)
    assert response.status_code == 200
    return response.json()


def test_fake_oauth_authorization_code_drives_role_specific_manifest(fake_oauth):
    verifier = "automation-test-verifier-with-sufficient-length"
    engineer_token = exchange_code(
        authorize_test_user("engineer", verifier=verifier),
        verifier=verifier,
    )["access_token"]
    finance_token = exchange_code(authorize_test_user("finance"))["access_token"]

    assert tool_names(engineer_token) == {
        "get_current_user",
        "search_service_incidents",
        "get_deployment_status",
        "create_incident_mitigation_plan",
    }
    assert tool_names(finance_token) == {
        "get_current_user",
        "search_budget_variances",
        "get_cost_center_status",
        "create_spend_mitigation_plan",
    }


def test_fake_oauth_refresh_token_preserves_identity(fake_oauth):
    token_response = exchange_code(authorize_test_user("finance"))
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "test-public-client",
            "refresh_token": token_response["refresh_token"],
        },
    )

    assert response.status_code == 200
    assert tool_names(response.json()["access_token"]) == {
        "get_current_user",
        "search_budget_variances",
        "get_cost_center_status",
        "create_spend_mitigation_plan",
    }


def test_fake_oauth_rejects_unregistered_redirect_uri(fake_oauth):
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-public-client",
            "redirect_uri": "https://attacker.example/callback",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "redirect_uri is not allowed"


def test_fake_oauth_authorization_code_is_single_use(fake_oauth):
    code = authorize_test_user("engineer")
    exchange_code(code)
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-public-client",
            "redirect_uri": "https://foundry.example/callback",
            "code": code,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_grant"


def test_fake_oauth_requires_mcp_scope(fake_oauth):
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-public-client",
            "redirect_uri": "https://foundry.example/callback",
            "scope": "offline_access",
            "test_user": "engineer",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Required scope is missing: mcp.access"


def test_fake_oauth_rejects_malformed_pkce_verifier(fake_oauth):
    code = authorize_test_user(
        "engineer",
        verifier="automation-test-verifier-with-sufficient-length",
    )
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "test-public-client",
            "redirect_uri": "https://foundry.example/callback",
            "code": code,
            "code_verifier": "not-ascii-\u00e9",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_grant"
