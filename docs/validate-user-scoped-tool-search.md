# Validate user-specific Tool Search results

## What this sample shows

This sample shows that two users can use the same Microsoft Foundry Toolbox and
ask the same question while receiving different tools based on their access.

- An Engineering user receives an Engineering incident tool.
- A Finance user receives a Finance budget tool.

Tool Search automatically selects from the tools available to the signed-in
user.

## Before you start

You need:

- Access to the Foundry project containing `UserScopedToolbox:1`
- A GitHub account
- Python 3.11 or later
- Azure CLI
- Git

The Toolbox, GitHub connection, and demo service must already be configured.
If you are setting up the demo, follow
[GitHub OAuth and Foundry setup](setup-guide.md).

## Install the sample

```powershell
git clone https://github.com/shpengmsft/foundry-toolbox-user-scoped-mcp-demo.git
cd .\foundry-toolbox-user-scoped-mcp-demo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[toolbox-test]"
```

## Run the validation

### User A

1. Sign in to Azure with User A:

   ```powershell
   az login
   ```

2. Make sure the Foundry GitHub connection is authorized with User A's GitHub
   account.
3. Run:

   ```powershell
   python .\tests\user_scoped_toolbox.py
   ```

4. Save the output.

### User B

1. Sign in to Azure with User B.
2. Authorize the same Foundry GitHub connection with User B's GitHub account.
3. Run the exact same script:

   ```powershell
   python .\tests\user_scoped_toolbox.py
   ```

4. Save the output.

Each user must use their own Azure and GitHub sign-in.

## Expected results

Both users use:

- The same Toolbox: `UserScopedToolbox:1`
- The same script
- The same question: `What is the largest current risk for my team?`

Engineering result:

```text
Same Toolbox: UserScopedToolbox:1
User-specific tool: search_service_incidents
Demo role: Engineering
Largest current risk: ENG-1042 - Elevated checkout latency after deployment
```

Finance result:

```text
Same Toolbox: UserScopedToolbox:1
User-specific tool: search_budget_variances
Demo role: Finance
Largest current risk: FIN-2041 - Cloud infrastructure is 18.4% over budget
```

## Conclusion

The Toolbox and question are identical, but Tool Search returns a different
role-specific tool:

| User | Tools returned by Tool Search | Tool used |
|---|---|---|
| Engineering | `get_current_user`, `search_service_incidents` | `search_service_incidents` |
| Finance | `get_current_user`, `search_budget_variances` | `search_budget_variances` |

This confirms that Tool Search accounts for the tools available to each
signed-in user.

The data returned by this sample is synthetic and intended only for
demonstration.
