# Validate user-scoped Tool Search

## Question

If two users have access to different MCP tools through the same Foundry
Toolbox, does Tool Search account for those differences?

## Answer

Yes. The MCP server builds `tools/list` for the authenticated user before
Toolbox performs tool selection. Tool Search can therefore discover only tools
available to that user. Tool authorization is checked again when the selected
tool is called.

## Demo

The two users share all of the following:

- Foundry project
- Toolbox name and version: `UserScopedToolbox:1`
- GitHub OAuth connection
- MCP endpoint
- Python script
- User question: `What is the largest current risk for my team?`

The only difference is the GitHub identity used by the OAuth connection.

```text
User -> Foundry Toolbox -> GitHub OAuth token -> Demo MCP
                                              -> GitHub /user
                                              -> demo role
                                              -> user-scoped tools/list
                                              -> Tool Search / tool call
```

Role mapping happens in the demo MCP, not in GitHub or the GitHub API.

## Prerequisites

Do not copy and run only `user_scoped_toolbox.py`. The script depends on this
repository and its optional Toolbox test packages.

Before running the validation:

- The demo MCP must be deployed and reachable.
- The Foundry project must contain the GitHub OAuth connection.
- `UserScopedToolbox:1` must be published with the demo MCP and Tool Search
  enabled.
- Both users must have access to the Foundry project and model deployment.
- Each user must authorize the OAuth connection with their own GitHub account.
- Python 3.11 or later and Azure CLI must be installed.

For complete service setup, follow
[GitHub OAuth and Foundry setup](setup-guide.md) first.

Clone the repository and install the required packages:

```powershell
git clone https://github.com/shpengmsft/foundry-toolbox-user-scoped-mcp-demo.git
cd .\foundry-toolbox-user-scoped-mcp-demo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[toolbox-test]"
```

Sign in to Azure as the Foundry user who will run the test:

```powershell
az login
```

The script uses `DefaultAzureCredential`, so the active Azure identity must
have access to the configured Foundry project.

The repository defaults target the published demo. For another project or
Toolbox, set these values before running:

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = "https://<resource>.services.ai.azure.com/api/projects/<project>"
$env:FOUNDRY_TOOLBOX_NAME = "UserScopedToolbox"
$env:FOUNDRY_TOOLBOX_VERSION = "1"
$env:FOUNDRY_MODEL_DEPLOYMENT = "gpt-5"
```

Repeat `az login` and GitHub OAuth authorization under the second user's own
accounts before running their comparison. Do not reuse the first user's Azure
or GitHub session.

## Quick validation

Use the same Toolbox and the same Tool Search query for both users:

```text
risk current risk user team
```

In the agent session, use this validation prompt:

```text
Call tool_search exactly once with query "risk current risk user team".
Return only the tool names and do not invoke call_tool.
```

1. User A signs in to Foundry and authorizes the connection with their GitHub
   account.
2. Invoke `tool_search` with the query above and save the returned tool names.
3. User B signs in to Foundry and authorizes the same connection with their own
   GitHub account.
4. Invoke `tool_search` with the exact same query and save the returned tool
   names.
5. Confirm that each result contains the shared identity tool and only that
   user's role-specific risk tool.

Expected and observed Tool Search results:

| Signed-in role | Tools returned by the same Tool Search query |
|---|---|
| Engineering | `get_current_user`, `search_service_incidents` |
| Finance | `get_current_user`, `search_budget_variances` |

`search_budget_variances` was absent from the Engineering result.
`search_service_incidents` was absent from the Finance result. The order shown
is the returned order; ranking scores were not included in the response.

This is the direct answer to the validation question: the Toolbox, version, and
query are identical, but Tool Search returns different tools because the
authenticated users receive different MCP catalogs.

### Validate invocation as well

After comparing Tool Search results, each user can run the same end-to-end
script:

```powershell
.\.venv\Scripts\python.exe .\tests\user_scoped_toolbox.py
```

No role argument or user identifier is supplied to the script. It identifies
the current user and invokes the role-specific tool selected for that user.

The end-to-end script may call a role tool directly when Toolbox has already
exposed or pinned that tool. Use the explicit `tool_search` comparison above
when the goal is specifically to validate Tool Search output.

## Observed results

User A:

```text
Same Toolbox: UserScopedToolbox:1
User-specific tool: search_service_incidents
Demo role: Engineering
Largest current risk: ENG-1042 - Elevated checkout latency after deployment
```

User B:

```text
Same Toolbox: UserScopedToolbox:1
User-specific tool: search_budget_variances
Demo role: Finance
Largest current risk: FIN-2041 - Cloud infrastructure is 18.4% over budget
```

The corresponding MCP `tools/list` results were:

| User | Role-specific catalog |
|---|---|
| Engineering | `search_service_incidents`, `get_deployment_status`, `create_incident_mitigation_plan` |
| Finance | `search_budget_variances`, `get_cost_center_status`, `create_spend_mitigation_plan` |

Both catalogs also contain `get_current_user`.

## How Tool Search stays user-scoped

1. Foundry sends the current user's OAuth token to the same MCP endpoint.
2. The MCP calls GitHub `/user` and reads the immutable numeric GitHub ID.
3. The MCP maps that ID to a demo role.
4. The MCP returns only that role's tools from `tools/list`.
5. Toolbox Tool Search searches the returned catalog.
6. Toolbox calls the selected tool through `call_tool` when progressive
   disclosure is active.
7. The MCP checks the user's authorization again during `tools/call`.

Tool Search does not search a shared union of Engineering and Finance tools.
Its candidate set is derived from the current user's MCP catalog.

In the observed Finance trace, Tool Search returned:

| Search query | Returned tools |
|---|---|
| `get_current_user` | `get_current_user` |
| `risk current risk user team` | `get_current_user`, `search_budget_variances` |
| `risk search user risk incidents vulnerabilities` | `search_budget_variances`, `get_current_user` |

Toolbox then invoked `get_current_user` and `search_budget_variances` through
`call_tool`. A separate Engineering Tool Search using the same
`risk current risk user team` query returned `get_current_user` and
`search_service_incidents`.

## What this proves

- One Toolbox version can produce different tool discovery results by user.
- Tool Search respects the user-scoped MCP catalog.
- The same natural-language question selects an Engineering tool for one user
  and a Finance tool for another.
- A tool hidden from discovery is also blocked during invocation.

The records and results in this repository are synthetic and intended only for
demonstration.
