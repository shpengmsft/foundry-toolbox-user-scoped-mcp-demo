from fastapi.testclient import TestClient

from user_scoped_mcp.app import app

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
        "who_am_i",
        "search_engineering_incidents",
        "inspect_deployment",
    }
    assert finance == {
        "who_am_i",
        "search_finance_reports",
        "summarize_cloud_costs",
    }


def test_admin_receives_all_tools():
    assert tool_names("demo-admin") == {
        "who_am_i",
        "search_engineering_incidents",
        "inspect_deployment",
        "search_finance_reports",
        "summarize_cloud_costs",
        "view_demo_access_matrix",
    }


def test_call_reauthorizes_hidden_tool():
    response = request(
        "tools/call",
        "demo-finance",
        {"name": "inspect_deployment", "arguments": {}},
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32003


def test_unknown_demo_token_is_rejected():
    response = request("tools/list", "not-a-user")
    assert response.status_code == 401


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
