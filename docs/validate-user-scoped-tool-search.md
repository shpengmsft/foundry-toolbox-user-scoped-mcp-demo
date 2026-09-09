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

## Validation steps

Both users run the same script:

```powershell
.\.venv\Scripts\python.exe .\tests\user_scoped_toolbox.py
```

The script asks `What is the largest current risk for my team?`. Do not mention
Tool Search in the prompt; Toolbox performs discovery automatically.

1. User A signs in to Foundry and authorizes the connection with their GitHub
   account.
2. User A runs the script and saves the output.
3. User B signs in to Foundry and authorizes the same connection with their own
   GitHub account.
4. User B runs the exact same script and saves the output.
5. Compare the selected tool and result. Use the execution traces when the Tool
   Search candidate list is also required.

Expected comparison:

| Signed-in role | Tool Search results | Tool called |
|---|---|---|
| Engineering | `search_service_incidents`, `get_current_user` | `search_service_incidents` |
| Finance | `search_budget_variances`, `get_current_user` | `search_budget_variances` |

`search_budget_variances` was absent from the Engineering result.
`search_service_incidents` was absent from the Finance result. Result order may
vary; ranking scores were not included in the response.

This is the direct answer to the validation question: the Toolbox, version, and
business question are identical, but Tool Search returns different tools
because the authenticated users receive different MCP catalogs.

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

The observed Finance trace returned `get_current_user` and
`search_budget_variances`, then invoked both tools. The Engineering comparison
returned `search_service_incidents` and `get_current_user`.

## What this proves

- One Toolbox version can produce different tool discovery results by user.
- Tool Search respects the user-scoped MCP catalog.
- The same natural-language question selects an Engineering tool for one user
  and a Finance tool for another.
- A tool hidden from discovery is also blocked during invocation.

The records and results in this repository are synthetic and intended only for
demonstration.
