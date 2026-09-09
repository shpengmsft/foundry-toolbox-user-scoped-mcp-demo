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

## Quick validation

1. User A signs in to Foundry and authorizes the connection with their GitHub
   account.
2. User A runs:

   ```powershell
   python .\tests\user_scoped_toolbox.py
   ```

3. User B signs in to Foundry and authorizes the same connection with their own
   GitHub account.
4. User B runs the exact same command.
5. Compare the `Same Toolbox`, `User-specific tool`, `Demo role`, and risk
   result lines.

No role argument or user identifier is supplied to the script.

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

## What this proves

- One Toolbox version can produce different tool discovery results by user.
- Tool Search respects the user-scoped MCP catalog.
- The same natural-language question selects an Engineering tool for one user
  and a Finance tool for another.
- A tool hidden from discovery is also blocked during invocation.

The records and results in this repository are synthetic and intended only for
demonstration.
