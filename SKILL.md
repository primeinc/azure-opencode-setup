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

Connect Azure AI Services models to OpenCode. Steps: discover resource, verify endpoint, configure provider, filter model list.

## Prerequisites

- `az` CLI authenticated (`az login`)
- OpenCode installed
- Azure subscription with AI Services/OpenAI resource + deployed models

## Workflow

| Step | Action | Reference |
|------|--------|-----------|
| 1 | Discover resource | `references/discovery-scripts.md` |
| 2 | Match endpoint to provider | Table below |
| 3 | Verify endpoint works | `references/verify-endpoint.md` |
| 4 | Set env var | Resource name only |
| 5 | `/connect` in OpenCode | Paste API key |
| 6 | Configure `opencode.json` | Whitelist + disabled_providers |
| 7 | Validate quota | `references/quota-validation.md` |

### Endpoint to provider mapping

| Endpoint | Provider | Env var |
|---|---|---|
| `*.cognitiveservices.azure.com` | `azure-cognitive-services` | `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` |
| `*.openai.azure.com` | `azure` | `AZURE_RESOURCE_NAME` |

### Config template

```json
{
  "disabled_providers": ["azure"],
  "provider": {
    "azure-cognitive-services": {
      "whitelist": ["gpt-4o", "gpt-5.2-chat", "deepseek-v3.2"],
      "models": {
        "custom-not-in-catalog": { "name": "Custom (Azure)" }
      }
    }
  }
}
```

- **`disabled_providers`**: Kill the other Azure provider to prevent duplicates
- **`whitelist`**: Lowercase deployment names (Azure is case-insensitive). [GH #9203](https://github.com/anomalyco/opencode/issues/9203)
- **`models`**: Only for deployments absent from built-in catalog

### Auth flow

1. Get key: `az cognitiveservices account keys list -g <RG> -n <RESOURCE> --query "key1" -o tsv`
2. Set env var (resource name, NOT key): see platform commands in discovery-scripts
3. `/connect` in OpenCode -> paste API key -> stored in `~/.local/share/opencode/auth.json`

## Troubleshooting

See `references/troubleshooting.md` — covers 404 deployment not found, 401 auth, wrong endpoint, catalog still showing, quota exceeded.
