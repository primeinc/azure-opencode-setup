# azure-opencode-setup

Connect Azure AI Services models to [OpenCode](https://opencode.ai/) in minutes. Discovers your resources, configures the provider, and filters the model list to only what you've deployed.

## What it does

Run one script → get a ready-to-paste `opencode.json` config block:

```powershell
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -Subscription "<SUB_ID>" -Resource "<RESOURCE>"
```
```bash
./scripts/emit-opencode-azure-cogsvc-config.sh --subscription "<SUB_ID>" --resource "<RESOURCE>"
```

The script discovers your Azure AI Services resource, lists all deployments, normalizes names (handles deployment ≠ model name mismatches like `kimi-k2` → `Kimi-K2-Thinking`), and prints JSON you paste directly into `opencode.json`.

## Install

```bash
npx skills add primeinc/azure-opencode-setup
```

<details>
<summary>Manual install (any agent)</summary>

Clone to your agent's skills directory:

```bash
# GitHub Copilot
git clone https://github.com/primeinc/azure-opencode-setup ~/.agents/skills/azure-opencode-setup

# Claude Code
git clone https://github.com/primeinc/azure-opencode-setup ~/.claude/skills/azure-opencode-setup

# OpenCode
git clone https://github.com/primeinc/azure-opencode-setup ~/.config/opencode/skills/azure-opencode-setup
```

</details>

## Use it

Start a conversation with your agent:

```
Set up Azure AI Services as my OpenCode provider
```

The skill activates automatically and walks through discovery, config, and verification.

## What's inside

```
azure-opencode-setup/
├── SKILL.md                              # Main skill (quick path + manual path + rules)
├── scripts/
│   ├── emit-opencode-azure-cogsvc-config.ps1  # PowerShell: emit ready-to-paste config
│   └── emit-opencode-azure-cogsvc-config.sh   # Bash: emit ready-to-paste config (requires jq)
└── references/
    ├── discovery-scripts.md              # Cross-subscription az CLI loops
    ├── verify-endpoint.md                # Smoke tests for both endpoint types
    ├── quota-validation.md               # Pre-flight capacity & quota checks
    └── troubleshooting.md                # Common errors + self-check diff command
```

## Prerequisites

- Azure CLI authenticated (`az login`)
- OpenCode installed
- An Azure subscription with an AI Services or OpenAI resource that has deployed models

## Key features

| Feature | Details |
|---------|---------|
| **Cross-subscription discovery** | Loops through all subs to find AI resources |
| **Automation script** | One command → ready-to-paste `opencode.json` block |
| **Whitelist filtering** | Deployment names + model name aliases for catalog compat |
| **Dual provider support** | Handles both `*.cognitiveservices.azure.com` and `*.openai.azure.com` |
| **Quota validation** | Catches exhausted quota before you hit 429s |
| **Self-check** | Diff command to find whitelist vs deployment drift |
| **Both shells** | PowerShell and bash scripts throughout |

## Troubleshooting quick ref

| Symptom | Likely cause |
|---------|-------------|
| 404 on model | Deployment name mismatch or not yet provisioned |
| 401 Unauthorized | Wrong API key or key not set via `/connect` |
| Full model catalog showing | Missing `whitelist` in provider config |
| 429 Too Many Requests | Quota exhausted — check `references/quota-validation.md` |

## License

MIT
