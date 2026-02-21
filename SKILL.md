---
name: azure-opencode-setup
description: >-
  Configure Azure AI Services (Cognitive Services or OpenAI) as a provider in OpenCode.
  USE FOR: setup azure opencode, connect azure to opencode, opencode.json azure provider,
  whitelist azure models, AZURE_COGNITIVE_SERVICES_RESOURCE_NAME, azure /connect,
  azure 404 401 troubleshoot opencode, az cognitiveservices opencode.
  DO NOT USE FOR: azure-deploy, microsoft-foundry, azure-resource-lookup, azure-prepare.
compatibility: Requires az CLI authenticated, OpenCode installed
---

# Azure AI + OpenCode Setup

## When to Use

USE FOR: setup azure opencode, connect azure models to opencode, azure cognitive services opencode,
azure openai provider config, opencode.json azure, whitelist azure models, filter azure model list,
AZURE_COGNITIVE_SERVICES_RESOURCE_NAME, AZURE_RESOURCE_NAME, azure /connect, azure 404 deployment,
azure 401 auth opencode, troubleshoot azure opencode, az cognitiveservices opencode.

DO NOT USE FOR: deploying Azure infrastructure (use azure-deploy), creating AI Foundry projects
(use microsoft-foundry), general Azure resource lookup (use azure-resource-lookup), application
deployment to Azure (use azure-prepare).

## Quick path (one command)

Run the automation script. All params optional — with zero args it scans every subscription and picks the resource with the most deployments:

```powershell
# PowerShell — dry run (prints JSON, changes nothing)
.\scripts\emit-opencode-azure-cogsvc-config.ps1

# PowerShell — apply (writes opencode.json, sets env var, verifies endpoint)
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -Apply

# Target a specific resource
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -Subscription "<SUB_ID>" -Resource "<RESOURCE>" -Apply
```
```bash
# Bash (requires jq) — same flags
./scripts/emit-opencode-azure-cogsvc-config.sh                    # dry run
./scripts/emit-opencode-azure-cogsvc-config.sh --apply            # apply
./scripts/emit-opencode-azure-cogsvc-config.sh --subscription "<SUB_ID>" --resource "<RESOURCE>" --apply
```

What the script does (in order):
1. Scans subscriptions → finds AI resources → picks the one with most deployments
2. Lists deployments → builds whitelist (deployment names + model names when they differ)
3. Verifies endpoint with a live API call
4. With `-Apply`: merges config into `opencode.json`, sets env var persistently, writes API key to `auth.json`

With `-Apply`, there are zero manual steps. The script writes directly to `auth.json` (same location `/connect` uses). Restart OpenCode to pick up changes.

## Manual path

| Step | Action | Reference |
|------|--------|-----------|
| 1 | Discover resource | [Discovery scripts](references/discovery-scripts.md) |
| 2 | Match endpoint → provider | Table below |
| 3 | Verify endpoint | [Verify endpoint](references/verify-endpoint.md) |
| 4 | Set env var (persistent) | Platform commands below |
| 5 | API key stored | `-Apply` writes to `auth.json` directly. Manual path: `/connect` in OpenCode. |
| 6 | Configure `opencode.json` | Whitelist + disabled_providers |
| 7 | Validate quota | [Quota validation](references/quota-validation.md) |

### Two Azure providers

OpenCode has two Azure providers. They use the same SDK (`@ai-sdk/azure`) but different endpoints and env vars:

| Endpoint pattern | Provider ID | Resource name env var | Catalog models |
|---|---|---|---|
| `*.cognitiveservices.azure.com` | `azure-cognitive-services` | `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` | 94 |
| `*.openai.azure.com` | `azure` | `AZURE_RESOURCE_NAME` | 95 |

Disable the one you don't use via `disabled_providers` to prevent duplicate model entries.

Source of truth for your endpoint: `az cognitiveservices account show -g <RG> -n <RES> --query properties.endpoint -o tsv`

### Auth flow

**Env var = resource name only.** The env var tells OpenCode: (a) this provider exists, (b) where to point the base URL.

**API key = `auth.json` only.** Stored at `~/.local/share/opencode/auth.json` (Windows: `%USERPROFILE%\.local\share\opencode\auth.json`). Written by `-Apply`, `/connect`, or `opencode auth login`.

> **Why not `AZURE_COGNITIVE_SERVICES_API_KEY`?** provider.toml declares it, but `provider.ts` line 901 only extracts the key when `env.length === 1`. Since this provider has 2 env vars, the key is always `undefined` via env. auth.json is the only working path.

Format: `{ "azure-cognitive-services": { "type": "api", "key": "<key>" } }`

### Set env var (persistent)

The env var holds the **resource name only**.

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

See [config template and whitelist rules](references/config-template.md) for a full `opencode.json` example, whitelist matching logic, and rules for naming entries.

### Multi-resource constraint

One provider config = one Azure resource. `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` points to exactly one resource.

If you have multiple resources:
- Pick the one with most deployments (script auto-picks if `--resource` omitted)
- To switch: change the env var and restart OpenCode
- OpenCode does not support multiple Azure resources in a single config

### Self-check: diff deployments vs whitelist

See [config template and whitelist rules](references/config-template.md#self-check-diff-deployments-vs-whitelist) for a PowerShell self-check script.

## Troubleshooting

See [troubleshooting](references/troubleshooting.md) — covers 404, 401, wrong endpoint, catalog still showing, quota exceeded, deployment/model name mismatch.

## Implementation contracts

See [contracts](references/contracts.md) — named invariants for whitelist casing, Windows paths, YAML shell patterns, and ACL implementation.
