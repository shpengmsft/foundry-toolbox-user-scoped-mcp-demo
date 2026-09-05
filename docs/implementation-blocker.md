# Why native Entra OAuth passthrough is currently blocked

## Goal

The intended demo uses one published Microsoft Foundry Toolbox and one remote
MCP endpoint. Different signed-in users should receive different successful
MCP `tools/list` responses, which should also cause Toolbox Tool Search to
return different tools for the same query.

For example:

- An Engineer sees incident and deployment tools.
- A Finance user sees budget and cost-center tools.
- An unassigned user sees only `get_current_user`.

This requires the MCP server to receive a trustworthy bearer token for the
current user. The server can then validate the token, read its immutable Entra
`oid` claim, map the user to a static role, and filter both `tools/list` and
`tools/call`.

## Why an existing hosted MCP server is insufficient

We first considered existing services such as GitHub MCP, Work IQ, and Fabric.
These services can enforce each user's permissions when a tool is called or
when data is returned. However, their published tool catalogs are generally
owned by the service and remain stable across users.

That behavior demonstrates user-specific **data authorization**, but it does
not reliably demonstrate the requirement in this sample:

> The same Toolbox version returns a different successful tool manifest, and
> therefore different Tool Search candidates, based on the signed-in user.

GitHub MCP can vary some capabilities based on scopes or server configuration,
but the demo needs a customer-controlled and deterministic mapping from user
identity to an intentionally different tool set. A custom MCP server is
therefore required.

## What has been implemented

The custom MCP server and its Azure deployment are complete:

1. It reads the bearer access token from the HTTP `Authorization` header.
2. It validates the JWT and extracts the Entra `oid`.
3. It compares that `oid` with static Engineer, Finance, and Administrator
   mappings.
4. It returns a role-specific `tools/list`.
5. It repeats authorization during `tools/call`, so hiding a tool is not the
   security boundary.
6. It returns only `get_current_user` for an unmapped user.

The implementation has been validated with manually acquired Entra tokens.
This proves that the MCP protocol behavior, JWT processing, role mapping, and
role-specific tool catalogs work.

What remains unproven is the native Entra end-to-end Foundry flow in which
Foundry acquires and forwards a separate Entra access token for each
interactive user.

## Why Foundry OAuth identity passthrough needs two app identities

Custom OAuth identity passthrough involves two OAuth roles:

1. **MCP resource application** - represents the protected MCP API and defines
   its audience and delegated scope, such as `mcp.access`.
2. **Foundry OAuth client application** - represents the client that starts the
   authorization-code flow, receives the redirect, redeems the authorization
   code, refreshes tokens, and supplies the resulting user token to the MCP
   connection.

The resource application answers, "Which API and scope is this token for?" The
client application answers, "Which application is requesting and redeeming the
user's authorization?"

Placing Azure API Management in front of the MCP server does not remove these
OAuth roles. APIM can validate and forward a token after one exists, but it
does not give Foundry a way to acquire a per-user token.

## The tenant-policy blocker

The tenant allows the app registrations to exist, but it blocks creation of
client secrets. The Foundry custom OAuth connection asks for:

- Client ID
- Client secret
- Authorization URL
- Token URL
- Refresh URL
- Scopes

Microsoft's documentation describes the client secret as optional depending on
the OAuth application. However, the documented Foundry configuration does not
provide a way to select or configure any of the normal secretless confidential
client alternatives:

- Certificate credential
- Federated credential or client assertion
- Managed identity

The documentation also does not state that Foundry uses PKCE when the client
secret is omitted, nor does the connection expose PKCE settings. A Microsoft
Entra public client must use a supported authorization-code flow, normally
with PKCE, rather than silently behaving as a confidential client without a
credential.

Consequently, we cannot claim that leaving the secret empty is a supported
Entra configuration. The current tenant policy prevents us from supplying the
credential used by the documented custom OAuth flow, while the Foundry
connection does not expose another client-authentication mechanism that the
tenant permits.

This is the blocking sequence:

```text
Existing hosted MCP
  -> stable provider-owned tool catalog
  -> cannot deterministically prove user-specific tools/list

Custom MCP
  -> can return a user-specific tool catalog
  -> requires a trustworthy user bearer token from Foundry

Foundry custom OAuth identity passthrough
  -> requires an OAuth resource and client
  -> documented setup uses a client secret for a confidential client

Tenant policy
  -> blocks creation of client secrets
  -> Foundry exposes no documented certificate, federation, managed identity,
     or PKCE configuration for this custom OAuth connection

Native Entra result
  -> server-side behavior works
  -> end-to-end per-user Foundry demonstration cannot currently be completed
     under the available tenant policy and documented product capabilities
```

## Automation workaround implemented in this repository

The repository includes a demo-only OAuth provider that implements the
authorization-code and refresh-token flows without a client secret. It issues
short-lived signed JWTs for deterministic Engineer, Finance, and Administrator
test identities.

This allows an automation test to cover:

1. Foundry producing an OAuth consent request.
2. Redirecting to an authorization endpoint.
3. Selecting a test identity.
4. Redeeming an authorization code.
5. Refreshing the resulting token.
6. Sending the access token to the MCP server.
7. Receiving identity-specific `tools/list` and Tool Search results.

The workaround proves the Foundry OAuth transport and Toolbox behavior. It
does not prove native Entra token issuance or tenant identity. The distinction
must remain explicit in test reports and demonstrations.

## Admin consent is a separate issue

The inability to grant tenant-wide admin consent is not automatically fatal.
Individual users can consent to a delegated scope when:

- The resource application's scope is configured to allow user consent.
- The tenant's user-consent policy permits that scope and application.
- The permission does not require administrator consent.

If tenant policy blocks user consent, an administrator must grant consent. Even
if consent is solved, however, it does not solve the missing OAuth client
credential.

## What would unblock the demo

Any one of the following would allow the end-to-end scenario to proceed:

1. A narrowly scoped tenant-policy exception permitting a short-lived secret
   on the Foundry OAuth client application.
2. An administrator-provided confidential client that the organization permits
   for this connection.
3. Documented Foundry support for a certificate, federated client assertion, or
   managed identity when redeeming custom OAuth authorization codes.
4. Confirmed and supported PKCE behavior for a Microsoft Entra public client
   when the Foundry client-secret field is empty.
5. A supported `user-entra-token` connection for this custom MCP audience in
   the target Foundry experience, avoiding the custom OAuth client credential
   entirely.

Until one of these paths is confirmed, the repository cannot honestly claim a
complete native Entra OAuth identity-passthrough demonstration in this tenant.
It can, however, run the same Foundry OAuth sequence against the included fake
provider for deterministic automation coverage.

## References

- [Set up MCP server authentication in Microsoft Foundry](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication)
- [Toolbox authentication in Microsoft Foundry](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication)
- [Configure restrictions on how applications can be configured in Microsoft Entra](https://learn.microsoft.com/entra/identity/enterprise-apps/configure-app-management-policies)
