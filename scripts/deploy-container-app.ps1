param(
    [Parameter(Mandatory)]
    [string]$ResourceGroup,

    [Parameter(Mandatory)]
    [string]$Location,

    [Parameter(Mandatory)]
    [string]$ContainerAppName,

    [ValidateSet("demo", "entra")]
    [string]$AuthMode = "entra",

    [string]$TenantId,
    [string]$Audience,
    [string]$EngineerUserObjectIds,
    [string]$FinanceUserObjectIds,
    [string]$AdminUserObjectIds
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required."
}

if ($AuthMode -eq "entra" -and (-not $TenantId -or -not $Audience)) {
    throw "TenantId and Audience are required in entra mode."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
az group create `
    --name $ResourceGroup `
    --location $Location `
    --output none

$environmentVariables = @("AUTH_MODE=$AuthMode")
if ($AuthMode -eq "entra") {
    $environmentVariables += "ENTRA_TENANT_ID=$TenantId"
    $environmentVariables += "ENTRA_AUDIENCE=$Audience"
    $environmentVariables += "ENTRA_REQUIRED_SCOPE=mcp.access"
    if ($EngineerUserObjectIds) {
        $environmentVariables += "ENGINEERING_USER_IDS=$EngineerUserObjectIds"
    }
    if ($FinanceUserObjectIds) {
        $environmentVariables += "FINANCE_USER_IDS=$FinanceUserObjectIds"
    }
    if ($AdminUserObjectIds) {
        $environmentVariables += "ADMIN_USER_IDS=$AdminUserObjectIds"
    }
}

az containerapp up `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --location $Location `
    --source $repoRoot `
    --ingress external `
    --target-port 8000 `
    --env-vars $environmentVariables `
    --output none

$fqdn = az containerapp show `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn `
    --output tsv

Write-Host "Health URL: https://$fqdn/health"
Write-Host "MCP URL:    https://$fqdn/mcp"
