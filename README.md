# Foundry Toolbox user-scoped MCP demo

This sample demonstrates one Azure AI Foundry Toolbox using the same remote MCP
endpoint while different signed-in users receive different successful
`tools/list` responses.

The server supports two authentication modes:

- `demo`: predefined bearer tokens; no Entra registration is required.
- `entra_passthrough`: validates a Toolbox-forwarded Entra JWT and maps its
  existing `oid` claim; no MCP-specific app registration is required.
- `entra`: validates a delegated Microsoft Entra access token and maps configured
  user object IDs to MCP tools using a dedicated MCP audience and scope.

The sample data is synthetic and every tool is read-only.

## Expected behavior

| Identity | Visible tools |
|---|---|
| Engineer | `get_current_user`, `search_service_incidents`, `get_deployment_status`, `create_incident_mitigation_plan` |
| Finance | `get_current_user`, `search_budget_variances`, `get_cost_center_status`, `create_spend_mitigation_plan` |
| Administrator | All Engineer and Finance tools |
| Unassigned | `get_current_user` only |

Tool descriptions deliberately use different engineering and finance terms.
This allows Toolbox Tool Search to demonstrate a different candidate set for
the same query and Toolbox version.

Use the same task for both roles:

> Investigate the largest current risk for my team and prepare a mitigation
> plan.

An Engineer discovers and calls the incident/deployment tool chain. A Finance
user discovers and calls the variance/cost-center tool chain. The tools query a
fixed synthetic dataset, but their results vary deterministically by input.

## Run locally without Entra

```powershell
cd C:\path\to\foundry-toolbox-user-scoped-mcp-demo
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\user-scoped-mcp
```

In another terminal:

```powershell
.\.venv\Scripts\python scripts\compare_tool_lists.py
```

Expected output:

```text
Only User A: ['create_incident_mitigation_plan', 'get_deployment_status', 'search_service_incidents']
Only User B: ['create_spend_mitigation_plan', 'get_cost_center_status', 'search_budget_variances']
Shared: ['get_current_user']
```

Demo bearer tokens are:

- `demo-engineer`
- `demo-finance`
- `demo-admin`

Demo mode proves MCP discovery behavior but is not a production authentication
mechanism and does not demonstrate OBO.

## Use an existing forwarded Entra JWT

If Toolbox already forwards the signed-in user's Entra JWT to the MCP endpoint,
the server can validate that token and authorize from its immutable `oid` claim.
The token does not need to have been issued for a newly registered MCP API for
this identity-only demo.

Deploy with:

```powershell
.\scripts\deploy-container-app.ps1 `
  -ResourceGroup "rg-user-scoped-mcp-demo" `
  -Location "westus3" `
  -ContainerAppName "user-scoped-mcp-demo" `
  -AuthMode entra_passthrough `
  -TenantId "<tenant-id>" `
  -EngineerUserObjectIds "<user-a-object-id>" `
  -FinanceUserObjectIds "<user-b-object-id>"
```

In this mode the server still validates the JWT signature, tenant issuer,
lifetime, and required claims. If the expected forwarded-token audience is
known, also pass `-Audience "<expected-aud>"` so it is validated.

This mode only works when Toolbox actually forwards the user JWT to the custom
endpoint. A platform trust policy can block forwarding Microsoft tokens to an
untrusted endpoint before the request reaches this server. Capture the incoming
request or Toolbox error first; app registration is unnecessary if the signed
JWT is already arriving.

## Entra architecture

```text
User A or User B
       |
       v
Foundry agent -> Toolbox -> UserEntraToken project connection
       |
       v
Azure Container Apps HTTPS endpoint
       |
       v
JWT validation -> static oid allowlist -> user-specific tools/list
```

For a dedicated MCP audience, the MCP server does not call a downstream API, so
one Entra app registration is enough. An additional client credential and OBO
exchange are needed only if the MCP server later calls Microsoft Graph or
another downstream API. When an existing signed JWT is forwarded,
`entra_passthrough` avoids the MCP-specific registration entirely.

## Create the Entra application

Prerequisites:

- Azure CLI authenticated to the target tenant.
- Permission to create app registrations and service principals.

Run:

```powershell
.\scripts\create-entra-app.ps1 -DisplayName "Foundry user-scoped MCP demo"
```

The script creates:

- Delegated scope `mcp.access`.
- The enterprise application/service principal.

Save the emitted tenant ID, audience, and application ID.

Find the immutable object IDs of the two test users:

```powershell
az ad user show --id "engineer@contoso.com" --query id --output tsv
az ad user show --id "finance@contoso.com" --query id --output tsv
```

The server deliberately authorizes by `oid`, not user name or email address,
because names and sign-in addresses can change.

## Deploy to Azure Container Apps

The simplest reproducible deployment uses `az containerapp up`, which builds the
Dockerfile and creates the required Container Apps resources:

```powershell
.\scripts\deploy-container-app.ps1 `
  -ResourceGroup "rg-user-scoped-mcp-demo" `
  -Location "westus3" `
  -ContainerAppName "user-scoped-mcp-demo" `
  -TenantId "<tenant-id>" `
  -Audience "api://<application-client-id>" `
  -EngineerUserObjectIds "<user-a-object-id>" `
  -FinanceUserObjectIds "<user-b-object-id>"
```

The server validates Entra tokens itself. Do not place credentials in the image
or repository.

For a no-registration protocol demo, deploy with:

```powershell
.\scripts\deploy-container-app.ps1 `
  -ResourceGroup "rg-user-scoped-mcp-demo" `
  -Location "westus3" `
  -ContainerAppName "user-scoped-mcp-demo" `
  -AuthMode demo
```

## Configure Foundry Toolbox

1. Create a project connection using **User Entra Token** authentication.
2. Set its target audience/resource to the MCP application's Application ID URI,
   such as `api://<application-client-id>`.
3. Add one remote MCP tool to the Toolbox:
   - Endpoint: `https://<container-app-fqdn>/mcp`
   - Authentication: the User Entra Token project connection
4. Publish one Toolbox version and use that same version for both users.
5. Sign in as User A and User B in separate sessions.
6. Compare raw `tools/list` output and run Tool Search prompts such as:
   - `Investigate the largest current risk for my team and prepare a mitigation plan`
   - `Find engineering deployment failures`
   - `Find confidential finance forecasts`

Both users must consent to the delegated `mcp.access` permission. If tenant
policy blocks user consent, an administrator must grant consent.

## Authorization behavior

The server validates:

- JWT signature against the tenant's OpenID keys.
- Issuer and audience.
- Token lifetime and required claims.
- Delegated `mcp.access` scope.

It maps the immutable token `oid` claim against the configured Engineering,
Finance, and Admin user lists during `tools/list`, then repeats the same
authorization during `tools/call`. JWT app-role claims are intentionally ignored
so roles issued for another audience cannot bypass the static mapping. Hiding a
tool is not the only security boundary.

## Troubleshooting

- `401`: missing, expired, incorrectly issued, or wrong-audience token.
- `403 Missing delegated scope`: the token does not contain `mcp.access`.
- In `entra_passthrough`, inspect the JWT's `aud` claim and configure
  `ENTRA_AUDIENCE` when possible. Skipping audience validation is appropriate
  only for this controlled identity-discovery demo.
- Only `get_current_user` appears: the user's `oid` is not in a configured
  persona list. Call it to obtain the `oid`, add that value to the Engineering
  or Finance list, and redeploy.
- User-list changes require a new Container Apps revision, but not a new token.
- If Foundry rejects Microsoft token forwarding to the endpoint as untrusted,
  verify that the current Toolbox/UserEntraToken feature is enabled in the
  selected region and that the connection targets the exact MCP audience.
- Tool Search must not reuse a manifest cached under another user. Capture both
  raw `tools/list` responses before diagnosing ranking behavior.

## Development

```powershell
python -m pip install -e ".[dev]"
ruff check .
pytest
docker build -t user-scoped-mcp-demo .
```

## Security

Demo tokens are intentionally public and must never be used for real data.
Production deployments should use `AUTH_MODE=entra`, HTTPS, least-privilege app
authorization configuration, and normal Azure monitoring practices.
