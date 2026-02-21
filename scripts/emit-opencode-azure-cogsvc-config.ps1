<#
.SYNOPSIS
  Discovers Azure AI Services deployments and emits a ready-to-paste opencode.json provider block.
.PARAMETER Subscription
  Azure subscription ID (required).
.PARAMETER Resource
  Azure AI Services resource name. If omitted, auto-picks the resource with most deployments.
.PARAMETER ResourceGroup
  Resource group. Auto-discovered if omitted.
.EXAMPLE
  .\emit-opencode-azure-cogsvc-config.ps1 -Subscription "98a49ff3-..." -Resource "ai-found-021426"
  .\emit-opencode-azure-cogsvc-config.ps1 -Subscription "98a49ff3-..."  # auto-pick
#>
param(
  [Parameter(Mandatory)][string]$Subscription,
  [string]$Resource,
  [string]$ResourceGroup
)
$ErrorActionPreference = "Stop"

az account set --subscription $Subscription | Out-Null

# Auto-discover resource if not specified
if (-not $Resource) {
  Write-Host "WARNING: No -Resource specified. Scanning subscription..." -ForegroundColor Yellow
  $accounts = az cognitiveservices account list `
    --query "[?kind=='AIServices' || kind=='OpenAI'].{name:name, rg:resourceGroup}" -o json | ConvertFrom-Json

  if (-not $accounts -or $accounts.Count -eq 0) {
    throw "No AIServices or OpenAI resources found in subscription $Subscription"
  }

  $best = $null; $bestCount = 0
  foreach ($acct in $accounts) {
    $count = [int](az cognitiveservices account deployment list -g $acct.rg -n $acct.name --query "length([])" -o tsv 2>$null)
    Write-Host "  $($acct.name) ($($acct.rg)): $count deployments" -ForegroundColor Gray
    if ($count -gt $bestCount) { $best = $acct; $bestCount = $count }
  }
  $Resource = $best.name; $ResourceGroup = $best.rg
  Write-Host "Selected: $Resource ($bestCount deployments)" -ForegroundColor Green

  if ($accounts.Count -gt 1) {
    Write-Host "WARNING: $($accounts.Count) resources found. Use -Resource to target a specific one." -ForegroundColor Yellow
    Write-Host "NOTE: One provider config = one resource. Only '$Resource' will be configured." -ForegroundColor Yellow
  }
}

# Resolve resource group
if (-not $ResourceGroup) {
  $ResourceGroup = az resource list --name $Resource --resource-type "Microsoft.CognitiveServices/accounts" `
    --query "[0].resourceGroup" -o tsv
}
if (-not $ResourceGroup) { throw "Could not find resource group for '$Resource'" }

# Get endpoint [MICROSOFT-NORMATIVE: source of truth for provider type]
$Endpoint = az cognitiveservices account show -g $ResourceGroup -n $Resource --query "properties.endpoint" -o tsv
if (-not $Endpoint) { throw "No endpoint for $Resource" }

# Determine provider from endpoint pattern [MICROSOFT-NORMATIVE]
if ($Endpoint -match 'cognitiveservices\.azure\.com') {
  $Provider = "azure-cognitive-services"
  $EnvVar = "AZURE_COGNITIVE_SERVICES_RESOURCE_NAME"
  $Disable = "azure"
} elseif ($Endpoint -match 'openai\.azure\.com') {
  $Provider = "azure"
  $EnvVar = "AZURE_RESOURCE_NAME"
  $Disable = "azure-cognitive-services"
} else {
  throw "Unrecognized endpoint pattern: $Endpoint"
}

# List deployments [MICROSOFT-NORMATIVE: deployment name is truth]
$deployments = az cognitiveservices account deployment list -g $ResourceGroup -n $Resource -o json | ConvertFrom-Json

# Build whitelist: deployment names (lowercased) + model names (lowercased) when they differ
# Rule: deployment name is primary key. Model name added for catalog compatibility.
$allNames = @()
foreach ($d in $deployments) {
  $allNames += $d.name.ToLower()
  $modelName = $d.properties.model.name.ToLower()
  if ($modelName -ne $d.name.ToLower()) {
    $allNames += $modelName
  }
}
$whitelist = $allNames | Sort-Object -Unique

# Build models block: only for non-catalog deployments
$customModels = @{}
foreach ($d in $deployments) {
  $depName = $d.name.ToLower()
  $modelName = $d.properties.model.name
  if ($depName -ne $modelName.ToLower() -and $modelName -notmatch '^(gpt|o[0-9]|text-)') {
    $customModels[$depName] = @{ name = "$modelName (Azure)" }
  }
}

# Emit metadata as comments
Write-Host "// ---- paste into opencode.json ----" -ForegroundColor Cyan
Write-Host "// Provider: $Provider | Resource: $Resource | Endpoint: $Endpoint" -ForegroundColor Cyan
Write-Host "// Env var to set: $EnvVar=$Resource" -ForegroundColor Cyan
Write-Host "// API key: run /connect in OpenCode -> paste key from:" -ForegroundColor Cyan
Write-Host "//   az cognitiveservices account keys list -g $ResourceGroup -n $Resource --query key1 -o tsv" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Cyan

# Emit JSON
$output = @{
  disabled_providers = @($Disable)
  provider = @{
    $Provider = @{
      whitelist = $whitelist
      models = $customModels
    }
  }
}
$output | ConvertTo-Json -Depth 6
