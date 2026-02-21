<#
.SYNOPSIS
  Discovers Azure AI Services deployments and emits/applies an opencode.json provider block.
  All parameters are optional. With zero args, scans all subscriptions and auto-picks the best resource.
.PARAMETER Subscription
  Azure subscription ID. If omitted, scans all subscriptions for AI resources.
.PARAMETER Resource
  Azure AI Services resource name. If omitted, auto-picks the resource with most deployments.
.PARAMETER ResourceGroup
  Resource group. Auto-discovered if omitted.
.PARAMETER Apply
  If set: writes config to opencode.json, sets env var persistently, verifies endpoint.
  If not set: prints JSON to stdout only (dry run).
.PARAMETER ConfigPath
  Path to opencode.json. Default: ~/.config/opencode/opencode.json
.EXAMPLE
  .\emit-opencode-azure-cogsvc-config.ps1                           # full auto, dry run
  .\emit-opencode-azure-cogsvc-config.ps1 -Apply                    # full auto, apply everything
  .\emit-opencode-azure-cogsvc-config.ps1 -Subscription "98a49..." -Resource "ai-found-021426"
  .\emit-opencode-azure-cogsvc-config.ps1 -Subscription "98a49..." -Apply
#>
param(
  [string]$Subscription,
  [string]$Resource,
  [string]$ResourceGroup,
  [switch]$Apply,
  [string]$ConfigPath = (Join-Path $env:USERPROFILE ".config\opencode\opencode.json")
)
$ErrorActionPreference = "Stop"

# ── Step 1: Find subscription ──────────────────────────────────────────────────
if (-not $Subscription) {
  Write-Host "Scanning all subscriptions for AI resources..." -ForegroundColor Yellow
  $subs = az account list --query "[].{id:id, name:name}" -o json | ConvertFrom-Json
  $found = @()
  foreach ($sub in $subs) {
    $accts = az cognitiveservices account list --subscription $sub.id `
      --query "[?kind=='AIServices' || kind=='OpenAI'].{name:name, rg:resourceGroup}" -o json 2>$null | ConvertFrom-Json
    if ($accts -and $accts.Count -gt 0) {
      foreach ($a in $accts) {
        $depCount = [int](az cognitiveservices account deployment list `
          --subscription $sub.id -g $a.rg -n $a.name --query "length([])" -o tsv 2>$null)
        $found += [PSCustomObject]@{
          SubId = $sub.id; SubName = $sub.name
          Resource = $a.name; RG = $a.rg; Deployments = $depCount
        }
        Write-Host "  $($sub.name) / $($a.name): $depCount deployments" -ForegroundColor Gray
      }
    }
  }
  if ($found.Count -eq 0) { throw "No AIServices or OpenAI resources found in any subscription" }

  $best = $found | Sort-Object Deployments -Descending | Select-Object -First 1
  $Subscription = $best.SubId
  $Resource = $best.Resource
  $ResourceGroup = $best.RG
  Write-Host "Selected: $($best.SubName) / $Resource ($($best.Deployments) deployments)" -ForegroundColor Green

  if ($found.Count -gt 1) {
    Write-Host "NOTE: $($found.Count) resources across $($subs.Count) subscriptions. Use -Subscription and -Resource to target a specific one." -ForegroundColor Yellow
  }
}

az account set --subscription $Subscription | Out-Null

# ── Step 2: Find resource (if subscription given but resource not) ─────────────
if (-not $Resource) {
  Write-Host "Scanning subscription for AI resources..." -ForegroundColor Yellow
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
}

# ── Step 3: Resolve resource group ────────────────────────────────────────────
if (-not $ResourceGroup) {
  $ResourceGroup = az resource list --name $Resource --resource-type "Microsoft.CognitiveServices/accounts" `
    --query "[0].resourceGroup" -o tsv
}
if (-not $ResourceGroup) { throw "Could not find resource group for '$Resource'" }

# ── Step 4: Get endpoint + determine provider [MICROSOFT-NORMATIVE] ──────────
$Endpoint = az cognitiveservices account show -g $ResourceGroup -n $Resource --query "properties.endpoint" -o tsv
if (-not $Endpoint) { throw "No endpoint for $Resource" }

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

# ── Step 5: List deployments [MICROSOFT-NORMATIVE: deployment name is truth] ──
$deployments = az cognitiveservices account deployment list -g $ResourceGroup -n $Resource -o json | ConvertFrom-Json

if ($deployments.Count -eq 0) {
  throw "No deployments found on $Resource. Deploy models first via Azure AI Foundry or az CLI."
}

Write-Host "`nDeployments on $Resource`:" -ForegroundColor White
foreach ($d in $deployments) {
  $dep = $d.name; $mod = $d.properties.model.name
  $mismatch = if ($dep.ToLower() -ne $mod.ToLower()) { " (model: $mod)" } else { "" }
  Write-Host "  $dep$mismatch" -ForegroundColor Gray
}

# ── Step 6: Build whitelist + models block ────────────────────────────────────
$allNames = @()
foreach ($d in $deployments) {
  $allNames += $d.name.ToLower()
  $modelName = $d.properties.model.name.ToLower()
  if ($modelName -ne $d.name.ToLower()) { $allNames += $modelName }
}
$whitelist = $allNames | Sort-Object -Unique

$customModels = @{}
foreach ($d in $deployments) {
  $depName = $d.name.ToLower()
  $modelName = $d.properties.model.name
  if ($depName -ne $modelName.ToLower() -and $modelName -notmatch '^(gpt|o[0-9]|text-)') {
    $customModels[$depName] = @{ name = "$modelName (Azure)" }
  }
}

# ── Step 7: Verify endpoint ──────────────────────────────────────────────────
$ApiKey = az cognitiveservices account keys list -g $ResourceGroup -n $Resource --query "key1" -o tsv
$testDeployment = ($deployments | Where-Object { $_.name -match '^gpt' } | Select-Object -First 1).name
if (-not $testDeployment) { $testDeployment = $deployments[0].name }

Write-Host "`nVerifying endpoint with deployment '$testDeployment'..." -ForegroundColor Yellow
try {
  $testUrl = "${Endpoint}openai/deployments/$testDeployment/chat/completions?api-version=2024-12-01-preview"
  $resp = Invoke-RestMethod -Uri $testUrl -Method Post `
    -Headers @{"api-key"=$ApiKey} -ContentType "application/json" `
    -Body '{"messages":[{"role":"user","content":"Say ok"}],"max_tokens":5}'
  Write-Host "Endpoint verified: $($resp.choices[0].message.content)" -ForegroundColor Green
} catch {
  Write-Host "WARNING: Endpoint verification failed: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Config will still be generated. Check troubleshooting docs." -ForegroundColor Yellow
}

# ── Step 8: Build output ─────────────────────────────────────────────────────
$providerBlock = @{
  disabled_providers = @($Disable)
  provider = @{
    $Provider = @{
      whitelist = $whitelist
      models = $customModels
    }
  }
}

$json = $providerBlock | ConvertTo-Json -Depth 6

if (-not $Apply) {
  # Dry run: print instructions + JSON
  Write-Host "`n// ---- paste into opencode.json ----" -ForegroundColor Cyan
  Write-Host "// Env var: $EnvVar=$Resource" -ForegroundColor Cyan
  Write-Host "// API key: /connect in OpenCode, paste output of:" -ForegroundColor Cyan
  Write-Host "//   az cognitiveservices account keys list -g $ResourceGroup -n $Resource --query key1 -o tsv" -ForegroundColor Cyan
  Write-Host ""
  Write-Output $json
} else {
  # ── Apply: merge into opencode.json ─────────────────────────────────────
  Write-Host "`nApplying configuration..." -ForegroundColor Yellow

  # 8a. Set env var persistently
  Write-Host "  Setting $EnvVar=$Resource (User scope)..." -ForegroundColor Gray
  [System.Environment]::SetEnvironmentVariable($EnvVar, $Resource, "User")
  $env:AZURE_COGNITIVE_SERVICES_RESOURCE_NAME = $Resource  # also set for current session

  # 8b. Merge into opencode.json
  if (Test-Path $ConfigPath) {
    $existing = Get-Content $ConfigPath -Raw | ConvertFrom-Json
  } else {
    $existing = [PSCustomObject]@{}
  }

  # Merge disabled_providers
  $existingDisabled = @()
  if ($existing.PSObject.Properties['disabled_providers']) {
    $existingDisabled = @($existing.disabled_providers)
  }
  if ($Disable -notin $existingDisabled) { $existingDisabled += $Disable }
  $existing | Add-Member -NotePropertyName 'disabled_providers' -NotePropertyValue $existingDisabled -Force

  # Merge provider block
  if (-not $existing.PSObject.Properties['provider']) {
    $existing | Add-Member -NotePropertyName 'provider' -NotePropertyValue ([PSCustomObject]@{}) -Force
  }
  $providerObj = [PSCustomObject]@{
    whitelist = $whitelist
    models = $customModels
  }
  $existing.provider | Add-Member -NotePropertyName $Provider -NotePropertyValue $providerObj -Force

  $existing | ConvertTo-Json -Depth 10 | Set-Content $ConfigPath -Encoding UTF8
  Write-Host "  Written to $ConfigPath" -ForegroundColor Green

  # 8c. Print remaining manual step
  Write-Host "`nDONE. One manual step remains:" -ForegroundColor Green
  Write-Host "  1. Open OpenCode" -ForegroundColor White
  Write-Host "  2. Run /connect -> select '$Provider'" -ForegroundColor White
  Write-Host "  3. Paste this API key:" -ForegroundColor White
  Write-Host "     $ApiKey" -ForegroundColor Cyan
  Write-Host "`n  Or copy it from:" -ForegroundColor Gray
  Write-Host "     az cognitiveservices account keys list -g $ResourceGroup -n $Resource --query key1 -o tsv" -ForegroundColor Gray
}
