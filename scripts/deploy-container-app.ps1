param(
    [Parameter(Mandatory)]
    [string]$ResourceGroup,

    [Parameter(Mandatory)]
    [string]$Location,

    [Parameter(Mandatory)]
    [string]$ContainerAppName,

    [ValidateSet("demo", "entra", "entra_passthrough", "fake_oauth", "github")]
    [string]$AuthMode = "entra",

    [string]$TenantId,
    [string]$Audience,
    [string]$EngineerUserObjectIds,
    [string]$FinanceUserObjectIds,
    [string]$AdminUserObjectIds,
    [string]$FakeOAuthClientId = "foundry-test-client",
    [string]$FakeOAuthRedirectUris = "http://localhost:8400/callback",
    [string]$FakeOAuthAudience = "user-scoped-mcp-demo",
    [string]$FakeOAuthIssuer,
    [ValidateSet("engineering", "finance", "unassigned")]
    [string]$GitHubDefaultRole = "finance",
    [string]$RegistryName,
    [string]$ContainerAppsEnvironment,
    [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required."
}

if ($AuthMode -in @("entra", "entra_passthrough") -and -not $TenantId) {
    throw "TenantId is required for Entra authentication."
}

if ($AuthMode -eq "entra" -and -not $Audience) {
    throw "TenantId and Audience are required in entra mode."
}

if ($AuthMode -eq "fake_oauth" -and -not $FakeOAuthIssuer) {
    throw "FakeOAuthIssuer is required in fake_oauth mode."
}

if ([bool]$RegistryName -ne [bool]$ContainerAppsEnvironment) {
    throw "RegistryName and ContainerAppsEnvironment must be supplied together."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
az group create `
    --name $ResourceGroup `
    --location $Location `
    --output none

$environmentVariables = @("AUTH_MODE=$AuthMode")
if ($AuthMode -in @("entra", "entra_passthrough")) {
    $environmentVariables += "ENTRA_TENANT_ID=$TenantId"
    if ($Audience) {
        $environmentVariables += "ENTRA_AUDIENCE=$Audience"
    }
    if ($AuthMode -eq "entra") {
        $environmentVariables += "ENTRA_REQUIRED_SCOPE=mcp.access"
    }
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
elseif ($AuthMode -eq "fake_oauth") {
    $environmentVariables += @(
        "FAKE_OAUTH_ISSUER=$($FakeOAuthIssuer.TrimEnd('/'))",
        "FAKE_OAUTH_CLIENT_ID=$FakeOAuthClientId",
        "FAKE_OAUTH_REDIRECT_URIS=$FakeOAuthRedirectUris",
        "FAKE_OAUTH_AUDIENCE=$FakeOAuthAudience"
    )
}
elseif ($AuthMode -eq "github") {
    $environmentVariables += "GITHUB_DEFAULT_ROLE=$GitHubDefaultRole"
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

if ($RegistryName) {
    $imageName = "$ContainerAppName`:$ImageTag"
    az acr build `
        --registry $RegistryName `
        --resource-group $ResourceGroup `
        --image $imageName `
        --file (Join-Path $repoRoot "Dockerfile") `
        $repoRoot `
        --no-logs `
        --output none

    $registryServer = az acr show `
        --name $RegistryName `
        --resource-group $ResourceGroup `
        --query loginServer `
        --output tsv
    $registryUsername = az acr credential show `
        --name $RegistryName `
        --resource-group $ResourceGroup `
        --query username `
        --output tsv
    $registryPassword = az acr credential show `
        --name $RegistryName `
        --resource-group $ResourceGroup `
        --query "passwords[0].value" `
        --output tsv
    $existingApp = az containerapp list `
        --resource-group $ResourceGroup `
        --query "[?name=='$ContainerAppName'].name | [0]" `
        --output tsv

    if ($existingApp) {
        az containerapp registry set `
            --name $ContainerAppName `
            --resource-group $ResourceGroup `
            --server $registryServer `
            --username $registryUsername `
            --password $registryPassword `
            --output none
        az containerapp update `
            --name $ContainerAppName `
            --resource-group $ResourceGroup `
            --image "$registryServer/$imageName" `
            --set-env-vars $environmentVariables `
            --output none
    }
    else {
        az containerapp create `
            --name $ContainerAppName `
            --resource-group $ResourceGroup `
            --environment $ContainerAppsEnvironment `
            --image "$registryServer/$imageName" `
            --registry-server $registryServer `
            --registry-username $registryUsername `
            --registry-password $registryPassword `
            --ingress external `
            --target-port 8000 `
            --env-vars $environmentVariables `
            --output none
    }
}
else {
    az containerapp up `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --location $Location `
        --source $repoRoot `
        --ingress external `
        --target-port 8000 `
        --env-vars $environmentVariables
}

$fqdn = az containerapp show `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn `
    --output tsv

Write-Host "Health URL: https://$fqdn/health"
Write-Host "MCP URL:    https://$fqdn/mcp"
if ($AuthMode -eq "fake_oauth") {
    Write-Host "Auth URL:   https://$fqdn/oauth/authorize"
    Write-Host "Token URL:  https://$fqdn/oauth/token"
    Write-Host "Discovery:  https://$fqdn/.well-known/openid-configuration"
}
