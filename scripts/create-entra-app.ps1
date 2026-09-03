param(
    [string]$DisplayName = "Foundry user-scoped MCP demo"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required."
}

$account = az account show --output json | ConvertFrom-Json
$tenantId = $account.tenantId
$app = az ad app create `
    --display-name $DisplayName `
    --sign-in-audience AzureADMyOrg `
    --output json | ConvertFrom-Json

$scopeId = [guid]::NewGuid().ToString()
$identifierUri = "api://$($app.appId)"

$payload = @{
    identifierUris = @($identifierUri)
    api = @{
        requestedAccessTokenVersion = 2
        oauth2PermissionScopes = @(
            @{
                id = $scopeId
                adminConsentDescription = "Access the user-scoped MCP demo as the signed-in user."
                adminConsentDisplayName = "Access user-scoped MCP demo"
                isEnabled = $true
                type = "User"
                userConsentDescription = "Allow the demo to identify you and list your authorized MCP tools."
                userConsentDisplayName = "Access user-scoped MCP demo"
                value = "mcp.access"
            }
        )
    }
}

az rest `
    --method PATCH `
    --uri "https://graph.microsoft.com/v1.0/applications/$($app.id)" `
    --headers "Content-Type=application/json" `
    --body ($payload | ConvertTo-Json -Depth 10 -Compress) | Out-Null

$servicePrincipal = az ad sp create --id $app.appId --output json | ConvertFrom-Json

[pscustomobject]@{
    TenantId = $tenantId
    ApplicationClientId = $app.appId
    ApplicationObjectId = $app.id
    ServicePrincipalObjectId = $servicePrincipal.id
    Audience = $identifierUri
    DelegatedScope = "$identifierUri/mcp.access"
} | Format-List
