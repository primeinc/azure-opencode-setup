# Quota & Capacity Validation

Pre-flight checks to run BEFORE configuring OpenCode, to confirm models actually work.

## Check deployed models are responding

```bash
# List all deployments and their status
az cognitiveservices account deployment list \
  -g <RG> -n <RESOURCE> \
  --query "[].{name:name, model:properties.model.name, status:properties.provisioningState, sku:sku.name, capacity:sku.capacity}" \
  -o table
```

Only `Succeeded` status deployments will respond. `Creating` or `Failed` will 404.

## Check subscription quota

```bash
# See quota usage for the resource's region
az cognitiveservices usage list \
  --location <REGION> \
  --subscription <SUB_ID> \
  --query "[?contains(name.value, 'OpenAI')].{name:name.value, used:currentValue, limit:limit}" \
  -o table
```

Pattern: `OpenAI.<SKU>.<model-name>` (e.g. `OpenAI.GlobalStandard.gpt-4o`).

If `used >= limit`, requests will return 429. Either increase quota or reduce other deployments.

## Quick capacity check (PowerShell)

```powershell
$sub = az account show --query id -o tsv
$region = "<REGION>"
$model = "<MODEL>"
$version = "<VERSION>"

# Check model availability in region
az cognitiveservices model list --location $region `
  --query "[?model.name=='$model'].{Version:model.version, SKUs:model.skus[].name}" `
  -o table

# Check remaining quota
az cognitiveservices usage list --location $region --subscription $sub `
  --query "[?contains(name.value, '$model')].{Metric:name.value, Used:currentValue, Limit:limit}" `
  -o table
```

## Common quota errors in OpenCode

| Symptom | Cause | Fix |
|---------|-------|-----|
| 429 Too Many Requests | Quota exhausted | Reduce capacity on other deployments or request increase |
| 404 Resource Not Found | Deployment not provisioned | Check `provisioningState` is `Succeeded` |
| Model works in portal but not OpenCode | Wrong deployment name in whitelist | Use exact deployment name (case-insensitive) |
| Intermittent failures | Shared capacity contention | Switch to Provisioned Throughput (PTU) SKU |
