import argparse
import asyncio
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

SYSTEM_PROMPT = (
    "Use the available Toolbox tools to investigate the user's current team risk. "
    "Use the role-specific search tool. Use only tool-returned data and respond in "
    "no more than three bullets. Do not call a mitigation-plan tool unless the user "
    "explicitly requests a plan. Do not add recommendations or ask a follow-up "
    "question. For incidents, a lower severity number means higher priority."
)

ROLE_EXPECTATIONS = {
    "engineering": {
        "expected": "search_service_incidents",
        "forbidden": "search_budget_variances",
    },
    "finance": {
        "expected": "search_budget_variances",
        "forbidden": "search_service_incidents",
    },
}


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


def canonical_tool_name(name: str) -> str:
    """Remove the Toolbox MCP server prefix from a generated function name."""
    return name.rsplit("___", maxsplit=1)[-1]


def response_tool_calls(response) -> list[str]:
    """Return function names recorded in an Agent Framework response."""
    calls: list[str] = []
    for message in response.messages:
        for content in message.contents:
            if content.type == "function_call" and content.name:
                calls.append(canonical_tool_name(content.name))
            elif content.type == "mcp_server_tool_call" and content.tool_name:
                calls.append(canonical_tool_name(content.tool_name))
    return calls


async def run_test(args: argparse.Namespace) -> None:
    expectation = ROLE_EXPECTATIONS[args.expected_role]
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
        name=args.toolbox_name,
        url=toolbox_mcp_url(
            args.endpoint,
            args.toolbox_name,
            args.toolbox_version,
        ),
        http_client=http_client,
        load_prompts=False,
    )

    try:
        await toolbox.connect()
        available_tools = sorted(
            canonical_tool_name(function.name) for function in toolbox.functions
        )

        assert expectation["expected"] in available_tools, (
            f"Expected {expectation['expected']} in Toolbox manifest; "
            f"received {available_tools}"
        )
        assert expectation["forbidden"] not in available_tools, (
            f"Unexpected {expectation['forbidden']} in Toolbox manifest; "
            f"received {available_tools}"
        )

        chat_client = FoundryChatClient(
            project_endpoint=args.endpoint,
            model=args.model,
            credential=credential,
        )
        agent = chat_client.as_agent(
            name="toolbox-agent",
            instructions=SYSTEM_PROMPT,
            tools=[toolbox],
        )
        response = await agent.run(messages=args.query, stream=False)
        tool_calls = response_tool_calls(response)

        assert expectation["expected"] in tool_calls, (
            f"Expected the agent to call {expectation['expected']}; "
            f"recorded calls were {tool_calls}"
        )
        assert expectation["forbidden"] not in tool_calls, (
            f"The agent called the other role's tool: {expectation['forbidden']}"
        )

        print(f"Role: {args.expected_role}")
        print(f"Toolbox Name and Version: {args.toolbox_name}:{args.toolbox_version}")
        print(f"Available tools: {', '.join(available_tools)}")
        print(f"Expected tool calls: {expectation['expected']}")
        print(f"Forbidden tool calls: {expectation['forbidden']}")
        print(f"Actual tool calls: {', '.join(tool_calls)}")
        print(f"Demo query: \"{args.query}\"")
        print(f"Demo response: \"{response.text}\"")
    finally:
        await toolbox.close()
        await http_client.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify user-specific tool discovery through a Foundry Toolbox."
    )
    parser.add_argument(
        "--expected-role",
        default=os.getenv("EXPECTED_ROLE", "engineering").lower(),
        choices=sorted(ROLE_EXPECTATIONS),
        help=(
            "Expected role for the connected GitHub user "
            "(default: EXPECTED_ROLE or engineering)."
        ),
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("FOUNDRY_PROJECT_ENDPOINT", DEFAULT_ENDPOINT),
    )
    parser.add_argument(
        "--toolbox-name",
        default=os.getenv("FOUNDRY_TOOLBOX_NAME", DEFAULT_TOOLBOX_NAME),
    )
    parser.add_argument(
        "--toolbox-version",
        default=os.getenv("FOUNDRY_TOOLBOX_VERSION", DEFAULT_TOOLBOX_VERSION),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("FOUNDRY_MODEL_DEPLOYMENT", DEFAULT_MODEL),
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_test(parse_args()))
