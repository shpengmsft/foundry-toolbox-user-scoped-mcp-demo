# Foundry Toolbox user-scoped Tool Search demo

This repository is a runnable proof that the **same Microsoft Foundry Toolbox**
can expose and select different MCP tools for different signed-in users.

Foundry forwards each user's GitHub OAuth token to the demo MCP server. The
server resolves the GitHub identity, assigns a demo role, and returns a
role-specific `tools/list` response:

- Engineering users receive engineering incident tools.
- Finance users receive finance budget tools.

Both users run the same script, use the same Toolbox version, and ask the same
question. The selected tool and result differ because tool discovery is scoped
to the authenticated user.

See [Validate user-scoped Tool Search](docs/validate-user-scoped-tool-search.md)
for the two-user demonstration and quick validation steps.
