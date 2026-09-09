import asyncio
import json
import os
from collections.abc import Callable

import httpx
from agent_framework import MCPStreamableHTTPTool
from agent_framework_foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

DEFAULT_ENDPOINT = (
    "https://egress-weu-resource.services.ai.azure.com/api/projects/egress-weu2"
)
DEFAULT_TOOLBOX_NAME = "UserScopedToolbox"
DEFAULT_TOOLBOX_VERSION = "1"
DEFAULT_MODEL = "gpt-5"
DEFAULT_QUERY = "What is the largest current risk for my team?"

ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", DEFAULT_ENDPOINT)
TOOLBOX_NAME = os.getenv("FOUNDRY_TOOLBOX_NAME", DEFAULT_TOOLBOX_NAME)
TOOLBOX_VERSION = os.getenv("FOUNDRY_TOOLBOX_VERSION", DEFAULT_TOOLBOX_VERSION)
MODEL = os.getenv("FOUNDRY_MODEL_DEPLOYMENT", DEFAULT_MODEL)
QUERY = os.getenv("DEMO_QUERY", DEFAULT_QUERY)

SYSTEM_PROMPT = (
    "First call get_current_user. Then call the role-specific search tool to answer "
    "the user's risk question. Use only tool-returned data. Return exactly two short "
    "lines. Line 1: You are <displayName> (GitHub user ID: <objectId>); your role is "
    "<role> in this demo. Line 2: Largest current risk: <concise risk summary>. "
    "Use ASCII characters only. Do not call a mitigation tool. For incidents, lower "
    "severity means higher priority."
)

ROLE_TOOLS = ("search_service_incidents", "search_budget_variances")


class ToolboxAuth(httpx.Auth):
    """Inject a fresh Foundry bearer token into every Toolbox MCP request."""

    def __init__(self, token_provider: Callable[[], str]):
        self._get_token = token_provider

    def auth_flow(self, request: httpx.Request):
        token = self._get_token()
        if not token:
            raise RuntimeError("The Foundry token provider returned an empty token")
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


def toolbox_mcp_url(endpoint: str, toolbox_name: str, toolbox_version: str) -> str:
    return (
        f"{endpoint.rstrip('/')}/toolboxes/{toolbox_name}/versions/"
        f"{toolbox_version}/mcp?api-version=v1"
    )


def response_tool_evidence(response) -> str:
    """Serialize calls and results so direct and Tool Search modes look the same."""
    evidence: list[object] = []
    for message in response.messages:
        for content in message.contents:
            if content.type in {
                "function_call",
                "function_result",
                "mcp_server_tool_call",
                "mcp_server_tool_result",
            }:
                evidence.append(
                    {
                        "type": content.type,
                        "name": content.name,
                        "tool_name": content.tool_name,
                        "arguments": content.arguments,
                        "result": content.result,
                        "output": content.output,
                    }
                )
    return json.dumps(evidence, default=str, sort_keys=True)


def selected_role_tool(evidence: str) -> str:
    matches = [name for name in ROLE_TOOLS if name in evidence]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one user-specific risk tool, "
            f"but found {matches or 'none'}."
        )
    return matches[0]


async def run_demo() -> None:
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential,
        "https://ai.azure.com/.default",
    )
    http_client = httpx.AsyncClient(
        auth=ToolboxAuth(token_provider),
        headers={"Foundry-Features": "Toolboxes=V1Preview"},
        timeout=120.0,
    )
    toolbox = MCPStreamableHTTPTool(
        name=TOOLBOX_NAME,
        url=toolbox_mcp_url(
            ENDPOINT,
            TOOLBOX_NAME,
            TOOLBOX_VERSION,
        ),
        http_client=http_client,
        load_prompts=False,
    )

    try:
        await toolbox.connect()
        chat_client = FoundryChatClient(
            project_endpoint=ENDPOINT,
            model=MODEL,
            credential=credential,
        )
        agent = chat_client.as_agent(
            name="toolbox-agent",
            instructions=SYSTEM_PROMPT,
            tools=[toolbox],
        )
        response = await agent.run(messages=QUERY, stream=False)
        evidence = response_tool_evidence(response)
        if "get_current_user" not in evidence:
            raise RuntimeError("The demo did not call get_current_user.")

        print(f"Same Toolbox: {TOOLBOX_NAME}:{TOOLBOX_VERSION}")
        print(f"User-specific tool: {selected_role_tool(evidence)}")
        print(response.text)
    finally:
        await toolbox.close()
        await http_client.aclose()

if __name__ == "__main__":
    asyncio.run(run_demo())
