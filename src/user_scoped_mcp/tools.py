import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .auth import Actor


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    required_role: str | None
    handler: Callable[[Actor, dict[str, Any]], dict[str, Any]]

    def manifest(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": True},
        }


EMPTY_INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Optional words used to filter the synthetic records.",
        }
    },
    "additionalProperties": False,
}


SERVICE_INCIDENTS = (
    {
        "id": "ENG-1042",
        "service": "checkout-api",
        "title": "Elevated checkout latency after deployment",
        "severity": 2,
        "status": "Investigating",
    },
    {
        "id": "ENG-1048",
        "service": "orders-worker",
        "title": "Order processing backlog",
        "severity": 3,
        "status": "Mitigating",
    },
)

DEPLOYMENTS = {
    "checkout-api": {
        "service": "checkout-api",
        "environment": "production",
        "version": "2026.09.02.3",
        "healthy": False,
        "failedChecks": ["latency-slo"],
    },
    "orders-worker": {
        "service": "orders-worker",
        "environment": "production",
        "version": "2026.09.01.7",
        "healthy": True,
        "failedChecks": [],
    },
}

BUDGET_VARIANCES = (
    {
        "id": "FIN-2041",
        "costCenter": "CC-100",
        "category": "Cloud infrastructure",
        "variancePercent": 18.4,
        "status": "Over budget",
    },
    {
        "id": "FIN-2046",
        "costCenter": "CC-200",
        "category": "Contractor services",
        "variancePercent": 7.2,
        "status": "Watch",
    },
)

COST_CENTERS = {
    "CC-100": {
        "costCenter": "CC-100",
        "name": "Digital commerce",
        "currency": "USD",
        "monthlyBudget": 70000,
        "actualSpend": 82880,
    },
    "CC-200": {
        "costCenter": "CC-200",
        "name": "Business operations",
        "currency": "USD",
        "monthlyBudget": 50000,
        "actualSpend": 53600,
    },
}


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _current_user(actor: Actor, _: dict[str, Any]) -> dict[str, Any]:
    if "Demo.Admin" in actor.roles:
        role = "Administrator"
    elif len(actor.roles) == 1:
        role = next(iter(actor.roles))
    elif actor.roles:
        role = "Multiple"
    else:
        role = "Unassigned"

    return {
        "objectId": actor.object_id,
        "displayName": actor.display_name,
        "role": role,
        "effectiveRoles": sorted(actor.roles),
        "identityProvider": actor.claims.get("auth_mode"),
    }


def _search_records(records: tuple[dict[str, Any], ...], query: str) -> list[dict[str, Any]]:
    words = query.lower().split()
    if not words:
        return list(records)
    matches = [
        record
        for record in records
        if all(word in json.dumps(record).lower() for word in words)
    ]
    return matches or list(records)


def _search_service_incidents(_: Actor, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    return {
        "query": query,
        "severityConvention": "Lower number means higher severity.",
        "incidents": _search_records(SERVICE_INCIDENTS, query),
    }


def _get_deployment_status(_: Actor, arguments: dict[str, Any]) -> dict[str, Any]:
    service = _required_string(arguments, "service")
    deployment = DEPLOYMENTS.get(service)
    if deployment is None:
        return {"service": service, "found": False}
    return {"found": True, "deployment": deployment}


def _create_incident_mitigation_plan(_: Actor, arguments: dict[str, Any]) -> dict[str, Any]:
    incident_id = _required_string(arguments, "incident_id")
    incident = next(
        (item for item in SERVICE_INCIDENTS if item["id"] == incident_id),
        None,
    )
    if incident is None:
        return {"incidentId": incident_id, "found": False}
    return {
        "incidentId": incident_id,
        "found": True,
        "plan": [
            f"Validate the current {incident['service']} deployment health.",
            "Compare the failing signal with the previous healthy version.",
            "Prepare a rollback recommendation and stakeholder update.",
        ],
    }


def _search_budget_variances(_: Actor, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    return {"query": query, "variances": _search_records(BUDGET_VARIANCES, query)}


def _get_cost_center_status(_: Actor, arguments: dict[str, Any]) -> dict[str, Any]:
    cost_center = _required_string(arguments, "cost_center")
    status = COST_CENTERS.get(cost_center.upper())
    if status is None:
        return {"costCenter": cost_center, "found": False}
    return {"found": True, "status": status}


def _create_spend_mitigation_plan(_: Actor, arguments: dict[str, Any]) -> dict[str, Any]:
    variance_id = _required_string(arguments, "variance_id")
    variance = next(
        (item for item in BUDGET_VARIANCES if item["id"] == variance_id),
        None,
    )
    if variance is None:
        return {"varianceId": variance_id, "found": False}
    return {
        "varianceId": variance_id,
        "found": True,
        "plan": [
            f"Review {variance['category']} charges for {variance['costCenter']}.",
            "Identify discretionary spend and owner-approved commitments.",
            "Prepare a forecast adjustment and cost-control recommendation.",
        ],
    }


TOOLS = (
    ToolDefinition(
        name="get_current_user",
        description=(
            "Show the signed-in user's immutable ID, display name, and assigned demo role."
        ),
        input_schema=EMPTY_INPUT_SCHEMA,
        required_role=None,
        handler=_current_user,
    ),
    ToolDefinition(
        name="search_service_incidents",
        description=(
            "Search engineering service incidents, production risks, failures, and alerts."
        ),
        input_schema=SEARCH_INPUT_SCHEMA,
        required_role="Engineering",
        handler=_search_service_incidents,
    ),
    ToolDefinition(
        name="get_deployment_status",
        description="Get deployment version and health details for an engineering service.",
        input_schema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name, such as checkout-api.",
                }
            },
            "required": ["service"],
            "additionalProperties": False,
        },
        required_role="Engineering",
        handler=_get_deployment_status,
    ),
    ToolDefinition(
        name="create_incident_mitigation_plan",
        description=(
            "Create a read-only engineering mitigation plan for a synthetic service incident."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "incident_id": {
                    "type": "string",
                    "description": "Synthetic incident ID, such as ENG-1042.",
                }
            },
            "required": ["incident_id"],
            "additionalProperties": False,
        },
        required_role="Engineering",
        handler=_create_incident_mitigation_plan,
    ),
    ToolDefinition(
        name="search_budget_variances",
        description=(
            "Search finance budget overruns, spending anomalies, forecasts, and risks."
        ),
        input_schema=SEARCH_INPUT_SCHEMA,
        required_role="Finance",
        handler=_search_budget_variances,
    ),
    ToolDefinition(
        name="get_cost_center_status",
        description="Get budget and actual spending details for a finance cost center.",
        input_schema={
            "type": "object",
            "properties": {
                "cost_center": {
                    "type": "string",
                    "description": "Synthetic cost center, such as CC-100.",
                }
            },
            "required": ["cost_center"],
            "additionalProperties": False,
        },
        required_role="Finance",
        handler=_get_cost_center_status,
    ),
    ToolDefinition(
        name="create_spend_mitigation_plan",
        description=(
            "Create a read-only finance mitigation plan for a synthetic budget variance."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "variance_id": {
                    "type": "string",
                    "description": "Synthetic variance ID, such as FIN-2041.",
                }
            },
            "required": ["variance_id"],
            "additionalProperties": False,
        },
        required_role="Finance",
        handler=_create_spend_mitigation_plan,
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
