---
name: azure-opencode-setup
description: >-
  Configure Azure AI Services (Cognitive Services or OpenAI) as a provider in OpenCode.
  USE FOR: setup azure opencode, connect azure models to opencode, azure cognitive services opencode,
  azure openai provider config, opencode.json azure, whitelist azure models, filter azure model list,
  AZURE_COGNITIVE_SERVICES_RESOURCE_NAME, AZURE_RESOURCE_NAME, azure /connect, azure 404 deployment,
  azure 401 auth opencode, troubleshoot azure opencode, az cognitiveservices opencode.
  DO NOT USE FOR: deploying Azure infrastructure (use azure-deploy), creating AI Foundry projects
  (use microsoft-foundry), general Azure resource lookup (use azure-resource-lookup), application
  deployment to Azure (use azure-prepare).
compatibility: Requires az CLI authenticated, OpenCode installed
---

# Azure AI + OpenCode Setup

## Quick path (one command)

Run the automation script. It discovers deployments and emits a ready-to-paste config block:

```powershell
# PowerShell
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -Subscription "<SUB_ID>" -Resource "<RESOURCE>"
```
```bash
# Bash (requires jq)
./scripts/emit-opencode-azure-cogsvc-config.sh --subscription "<SUB_ID>" --resource "<RESOURCE>"
```

Omit `--resource` to auto-pick the resource with most deployments. Script warns if multiple resources exist.

Paste the JSON output into `opencode.json`. Then run `/connect` in OpenCode to store the API key.

## Manual path

| Step | Action | Reference |
|------|--------|-----------|
| 1 | Discover resource | `references/discovery-scripts.md` |
| 2 | Match endpoint → provider | Table below |
| 3 | Verify endpoint | `references/verify-endpoint.md` |
| 4 | Set env var (persistent) | Platform commands below |
| 5 | `/connect` in OpenCode | Paste API key (stored in `auth.json`, NOT env var) |
| 6 | Configure `opencode.json` | Whitelist + disabled_providers |
| 7 | Validate quota | `references/quota-validation.md` |

### Endpoint → provider mapping [MICROSOFT-NORMATIVE]

| Endpoint pattern | Provider | Env var |
|---|---|---|
| `*.cognitiveservices.azure.com` | `azure-cognitive-services` | `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` |
| `*.openai.azure.com` | `azure` | `AZURE_RESOURCE_NAME` |

Source of truth: `az cognitiveservices account show -g <RG> -n <RES> --query properties.endpoint -o tsv`

### Set env var (persistent) [PROPOSED]

The env var holds the **resource name only**. API key goes through `/connect`.

**Windows (PowerShell):**
```powershell
setx AZURE_COGNITIVE_SERVICES_RESOURCE_NAME "<RESOURCE>"
# Restart terminal for setx to take effect
```

**macOS (zsh):**
```zsh
echo 'export AZURE_COGNITIVE_SERVICES_RESOURCE_NAME="<RESOURCE>"' >> ~/.zshrc
source ~/.zshrc
```

**Linux (bash):**
```bash
echo 'export AZURE_COGNITIVE_SERVICES_RESOURCE_NAME="<RESOURCE>"' >> ~/.bashrc
source ~/.bashrc
```

### Config template

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

### Whitelist rules [PROPOSED]

1. **Deployment name is truth.** Every deployment name (lowercased) goes in the whitelist.
2. **Model name added when it differs.** If Azure metadata shows `model.name` ≠ `deployment.name`, add the model name (lowercased) too. Example: deployment `kimi-k2` → model `Kimi-K2-Thinking` → whitelist gets both `kimi-k2` and `kimi-k2-thinking`.
3. **Include all deployments.** Don't skip embeddings or utility models (`text-embedding-3-small`, `model-router`).
4. **`models` block** only for deployments absent from the built-in catalog. Gives them a display name in `/models`.

### Multi-resource constraint [PROPOSED]

One provider config = one Azure resource. `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` points to exactly one resource.

If you have multiple resources:
- Pick the one with most deployments (script auto-picks if `--resource` omitted)
- To switch: change the env var and restart OpenCode
- OpenCode does not support multiple Azure resources in a single config

### Self-check: diff deployments vs whitelist

```powershell
# Compare Azure deployments to opencode.json whitelist
$deployed = az cognitiveservices account deployment list -g <RG> -n <RES> `
  --query "[].name" -o json | ConvertFrom-Json | ForEach-Object { $_.ToLower() } | Sort-Object
$whitelist = (Get-Content ~/.config/opencode/opencode.json | ConvertFrom-Json).provider.'azure-cognitive-services'.whitelist | Sort-Object
$missing = $deployed | Where-Object { $_ -notin $whitelist }
if ($missing) { Write-Host "MISSING from whitelist: $($missing -join ', ')" -ForegroundColor Red }
else { Write-Host "Whitelist matches all deployments" -ForegroundColor Green }
```

## Troubleshooting

See `references/troubleshooting.md` — covers 404, 401, wrong endpoint, catalog still showing, quota exceeded, deployment/model name mismatch.
