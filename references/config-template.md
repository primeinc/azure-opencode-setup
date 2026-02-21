# Config Template and Whitelist Rules

## opencode.json example

```json
{
  "disabled_providers": ["azure"],
  "provider": {
    "azure-cognitive-services": {
      "whitelist": [
        "gpt-4o",
        "gpt-5.2-chat",
        "deepseek-v3.2",
        "kimi-k2",
        "kimi-k2-thinking",
        "text-embedding-3-small"
      ],
      "models": {
        "kimi-k2": { "name": "Kimi-K2-Thinking (Azure)" }
      }
    }
  }
}
```

## Whitelist matching logic

Whitelist entries are matched against `modelID` from the models.dev catalog (94 entries for `azure-cognitive-services`). Not deployment names directly. Also supports `blacklist`.

```ts
// provider.ts — the actual matching logic
if (configProvider?.whitelist && !configProvider.whitelist.includes(modelID))
  delete provider.models[modelID]
```

## Whitelist rules

1. **Use catalog names.** Entries must match models.dev catalog IDs (e.g., `kimi-k2-thinking`, not `kimi-k2`). The `-Apply` script lowercases deployment and model names, aligning with catalog IDs.
2. **Add deployment name too when it differs.** Covers cases where OpenCode routes by deployment name (e.g., `kimi-k2` deployment and `kimi-k2-thinking` catalog name — add both).
3. **Include all deployments.** Don't skip embeddings or utility models (`text-embedding-3-small`, `model-router`).
4. **`models` block** only for deployments absent from the built-in catalog. Gives them a display name in `/models`.

## Self-check: diff deployments vs whitelist

```powershell
# Compare Azure deployments to opencode.json whitelist
$deployed = az cognitiveservices account deployment list -g <RG> -n <RES> `
  --query "[].name" -o json | ConvertFrom-Json | ForEach-Object { $_.ToLower() } | Sort-Object
$whitelist = (Get-Content ~/.config/opencode/opencode.json | ConvertFrom-Json).provider.'azure-cognitive-services'.whitelist | Sort-Object
$missing = $deployed | Where-Object { $_ -notin $whitelist }
if ($missing) { Write-Host "MISSING from whitelist: $($missing -join ', ')" -ForegroundColor Red }
else { Write-Host "Whitelist matches all deployments" -ForegroundColor Green }
```
