# azure-opencode-setup

Connect Azure AI Services models to [OpenCode](https://opencode.ai/) in minutes. Discovers your resources, configures the provider, and filters the model list to only what you've deployed.

## What it does

Run one script with zero args → get a fully configured OpenCode:

```powershell
# Dry run: prints what it would do
.\scripts\emit-opencode-azure-cogsvc-config.ps1

# Apply: writes opencode.json, sets env var, verifies endpoint
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -Apply
```
```bash
./scripts/emit-opencode-azure-cogsvc-config.sh           # dry run
./scripts/emit-opencode-azure-cogsvc-config.sh --apply    # apply
```

The script scans all Azure subscriptions, finds AI resources, picks the one with the most deployments, normalizes names (handles deployment ≠ model name mismatches like `kimi-k2` → `Kimi-K2-Thinking`), verifies the endpoint, and writes the config. Only manual step: `/connect` in OpenCode to paste the API key.

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
