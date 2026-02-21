---
name: azure-opencode-setup
description: Configure Azure AI Services (Cognitive Services or OpenAI) as a provider in OpenCode. Use when setting up Azure models in opencode, troubleshooting Azure provider auth or endpoint errors, deploying models to Azure AI Foundry for use with opencode, or limiting the Azure model list to deployed models only. Covers az CLI discovery, env vars, /connect auth, opencode.json provider config, whitelist filtering, and endpoint verification.
---

# Azure AI + OpenCode Setup

Set up Azure AI Services models as an OpenCode provider.

## Prerequisites

- Azure CLI (`az`) authenticated
- OpenCode installed
- An Azure subscription with an AI Services or OpenAI resource with deployed models

## Workflow

### 1. Discover the Azure resource

If you don't know which subscription has AI resources, loop through all of them. See `references/discovery-scripts.md` for full cross-subscription search scripts.

```bash
# Quick: search current subscription
az cognitiveservices account list \
  --query "[].{name:name, kind:kind, endpoint:properties.endpoint, rg:resourceGroup}" -o table

# Or set a specific subscription first
az account set --subscription "<SUBSCRIPTION_ID>"
```

Then list deployments on the resource to find available models:

```bash
az cognitiveservices account deployment list \
  -g <RG> -n <RESOURCE> \
  --query "[].{deployment:name, model:properties.model.name, sku:sku.name}" -o table
```

### 2. Determine provider by endpoint pattern

| Endpoint | OpenCode provider | Env var |
|---|---|---|
| `*.cognitiveservices.azure.com` | `azure-cognitive-services` | `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` |
| `*.openai.azure.com` | `azure` | `AZURE_RESOURCE_NAME` |

### 3. List deployed models

```bash
az cognitiveservices account deployment list \
  -g <RG> -n <RESOURCE> \
  --query "[].{deployment:name, model:properties.model.name}" -o table
```

Only deployed models work. Others will 404.

### 4. Get API key

```bash
az cognitiveservices account keys list -g <RG> -n <RESOURCE> --query "key1" -o tsv
```

### 5. Verify endpoint

See `references/verify-endpoint.md` for smoke test commands (PowerShell and bash).

### 6. Set env var (resource name only, NOT the key)

**Windows:**
```powershell
[System.Environment]::SetEnvironmentVariable("AZURE_COGNITIVE_SERVICES_RESOURCE_NAME", "<RESOURCE>", "User")
```

**Linux/macOS:**
```bash
export AZURE_COGNITIVE_SERVICES_RESOURCE_NAME=<RESOURCE>
```

### 7. Connect API key in OpenCode

1. Launch opencode
2. `/connect` -> search **Azure Cognitive Services** (or **Azure** for `*.openai.azure.com`)
3. Paste API key

Key is stored in `~/.local/share/opencode/auth.json`.

### 8. Configure opencode.json

```json
{
  "disabled_providers": ["azure"],
  "provider": {
    "azure-cognitive-services": {
      "whitelist": ["gpt-4o", "gpt-5.2-chat", "deepseek-v3.2"],
      "models": {
        "custom-deployment-not-in-catalog": { "name": "My Custom (Azure)" }
      }
    }
  }
}
```

Key options:
- **`disabled_providers`**: Disable `azure` if using `azure-cognitive-services` (prevents duplicate model entries)
- **`whitelist`**: Restrict `/models` list to only deployed models. Use lowercase names (Azure is case-insensitive). Undocumented feature per [GH #9203](https://github.com/anomalyco/opencode/issues/9203)
- **`models`**: Only needed for deployments not in the built-in catalog

### 9. Select model

Restart opencode, then `/models` or set default:

```json
{
  "model": "azure-cognitive-services/gpt-5.2-chat"
}
```

## Troubleshooting

See `references/troubleshooting.md` for common errors (404 deployment not found, 401 auth, wrong endpoint, full catalog still showing).
