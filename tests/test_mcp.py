from types import SimpleNamespace

import jwt
from fastapi.testclient import TestClient

from user_scoped_mcp.app import app
from user_scoped_mcp.auth import Actor, _actor_from_entra_token
from user_scoped_mcp.config import Settings
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
        assert kwargs["audience"] is None
        assert kwargs["options"]["verify_aud"] is False
        return {
            "oid": "engineer-oid",
            "name": "Engineer",
            "aud": "existing-foundry-audience",
            "roles": ["Finance"],
        }

    monkeypatch.setattr(jwt, "PyJWKClient", FakeJwkClient)
    monkeypatch.setattr(jwt, "decode", fake_decode)

    actor = _actor_from_entra_token("signed-jwt", settings)
    assert actor.object_id == "engineer-oid"
    assert actor.roles == frozenset({"Engineering"})
