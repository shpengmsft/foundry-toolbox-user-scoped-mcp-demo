import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .auth import Actor


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    required_role: str | None
    handler: Callable[[Actor, dict[str, Any]], dict[str, Any]]

    def manifest(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        }


def _identity(actor: Actor, _: dict[str, Any]) -> dict[str, Any]:
    return {
        "objectId": actor.object_id,
        "displayName": actor.display_name,
        "roles": sorted(actor.roles),
    }


def _engineering_incidents(_: Actor, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "incidents": [
            {"id": "ENG-1042", "title": "Deployment health probe failed", "severity": 2},
            {"id": "ENG-1048", "title": "Build agent capacity warning", "severity": 3},
        ]
    }


def _deployment(_: Actor, __: dict[str, Any]) -> dict[str, Any]:
    return {"environment": "demo-production", "version": "2026.09.02", "healthy": True}


def _finance_reports(_: Actor, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "reports": [
            {"name": "FY26 Q1 forecast", "status": "Draft"},
            {"name": "August cloud spend", "status": "Final"},
        ]
    }


def _cloud_costs(_: Actor, __: dict[str, Any]) -> dict[str, Any]:
    return {"currency": "USD", "month": "2026-08", "total": 12840.15}


def _access_matrix(_: Actor, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "roles": {
            "Engineering": ["search_engineering_incidents", "inspect_deployment"],
            "Finance": ["search_finance_reports", "summarize_cloud_costs"],
            "Demo.Admin": ["view_demo_access_matrix"],
        }
    }


TOOLS = (
    ToolDefinition(
        name="who_am_i",
        description="Show the signed-in user identity and effective demo roles.",
        required_role=None,
        handler=_identity,
    ),
    ToolDefinition(
        name="search_engineering_incidents",
        description=(
            "Search private engineering incidents, deployment failures, and service alerts."
        ),
        required_role="Engineering",
        handler=_engineering_incidents,
    ),
    ToolDefinition(
        name="inspect_deployment",
        description="Inspect the current application deployment, version, and health status.",
        required_role="Engineering",
        handler=_deployment,
    ),
    ToolDefinition(
        name="search_finance_reports",
        description="Search confidential finance forecasts, budgets, and quarterly reports.",
        required_role="Finance",
        handler=_finance_reports,
    ),
    ToolDefinition(
        name="summarize_cloud_costs",
        description="Summarize cloud costs, spending, budgets, and financial variance.",
        required_role="Finance",
        handler=_cloud_costs,
    ),
    ToolDefinition(
        name="view_demo_access_matrix",
        description="View the demo role-to-tool authorization matrix.",
        required_role="Demo.Admin",
        handler=_access_matrix,
    ),
)


def visible_tools(actor: Actor) -> list[ToolDefinition]:
    return [
        tool
        for tool in TOOLS
        if tool.required_role is None or tool.required_role in actor.roles
    ]


def call_tool(actor: Actor, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = next((candidate for candidate in TOOLS if candidate.name == name), None)
    if tool is None:
        raise LookupError(f"Unknown tool: {name}")
    if tool.required_role is not None and tool.required_role not in actor.roles:
        raise PermissionError(f"The current user is not authorized to call {name}")

    result = tool.handler(actor, arguments)
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
        "structuredContent": result,
        "isError": False,
    }
