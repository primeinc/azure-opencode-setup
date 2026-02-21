# Azure Resource Discovery Scripts

Practical az CLI commands to find AI Services resources and deployments across all subscriptions.

## Find AI resources across all subscriptions

When you don't know which subscription has AI resources:

### PowerShell

```powershell
$subs = az account list --query "[].id" -o tsv
foreach ($sub in $subs) {
  $result = az cognitiveservices account list --subscription $sub `
    --query "[].{name:name, kind:kind, endpoint:properties.endpoint, rg:resourceGroup}" `
    -o json 2>$null | ConvertFrom-Json
  if ($result -and $result.Count -gt 0) {
    Write-Host "=== Subscription: $sub ==="
    $result | ConvertTo-Json
  }
}
```

### Bash

```bash
for sub in $(az account list --query "[].id" -o tsv); do
  result=$(az cognitiveservices account list --subscription "$sub" \
    --query "[].{name:name, kind:kind, endpoint:properties.endpoint, rg:resourceGroup}" \
    -o json 2>/dev/null)
  if [ "$result" != "[]" ] && [ -n "$result" ]; then
    echo "=== Subscription: $sub ==="
    echo "$result"
  fi
done
```

Look for resources with `kind` of `AIServices` or `OpenAI`.

## List all deployments on a resource

```bash
az cognitiveservices account deployment list \
  -g <RESOURCE_GROUP> -n <RESOURCE_NAME> \
  --query "[].{deployment:name, model:properties.model.name, version:properties.model.version, sku:sku.name}" \
  -o table
```

## List deployments across all resources in a subscription

### PowerShell

```powershell
az account set --subscription "<SUBSCRIPTION_ID>"
$accounts = az cognitiveservices account list `
  --query "[?kind=='AIServices' || kind=='OpenAI'].{name:name, rg:resourceGroup}" -o json | ConvertFrom-Json

foreach ($acct in $accounts) {
  $deps = az cognitiveservices account deployment list `
    -g $acct.rg -n $acct.name `
    --query "[].{deployment:name, model:properties.model.name, version:properties.model.version, sku:sku.name}" `
    -o json 2>$null | ConvertFrom-Json
  if ($deps -and $deps.Count -gt 0) {
    Write-Host "=== $($acct.name) (rg: $($acct.rg)) ==="
    $deps | Format-Table -AutoSize
  }
}
```

### Bash

```bash
az account set --subscription "<SUBSCRIPTION_ID>"
az cognitiveservices account list \
  --query "[?kind=='AIServices' || kind=='OpenAI'].[name, resourceGroup]" -o tsv |
while IFS=$'\t' read -r name rg; do
  deps=$(az cognitiveservices account deployment list \
    -g "$rg" -n "$name" \
    --query "[].{deployment:name, model:properties.model.name}" -o table 2>/dev/null)
  if [ -n "$deps" ]; then
    echo "=== $name (rg: $rg) ==="
    echo "$deps"
    echo
  fi
done
```

## Get API keys

```bash
az cognitiveservices account keys list -g <RG> -n <RESOURCE> -o json
# Returns: { "key1": "...", "key2": "..." }
# Use either key. key2 is a backup for rotation.
```

## Build a whitelist from deployed models

Generate the `whitelist` array for opencode.json from your actual deployments:

### PowerShell

```powershell
$deps = az cognitiveservices account deployment list `
  -g <RG> -n <RESOURCE> `
  --query "[].name" -o json | ConvertFrom-Json
$whitelist = ($deps | ForEach-Object { "`"$($_.ToLower())`"" }) -join ", "
Write-Host "whitelist: [$whitelist]"
```

### Bash

```bash
az cognitiveservices account deployment list \
  -g <RG> -n <RESOURCE> \
  --query "[].name" -o tsv | tr '[:upper:]' '[:lower:]' | \
  awk '{printf "\"%s\", ", $0}' | sed 's/, $//'
```

## Pick the resource with most deployments

```powershell
$accounts = az cognitiveservices account list `
  --query "[?kind=='AIServices' || kind=='OpenAI'].{name:name, rg:resourceGroup}" -o json | ConvertFrom-Json
foreach ($a in $accounts) {
  $c = az cognitiveservices account deployment list -g $a.rg -n $a.name --query "length([])" -o tsv 2>$null
  Write-Host "$($a.name): $c deployments"
}
```
