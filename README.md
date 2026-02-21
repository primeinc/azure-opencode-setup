# azure-opencode-setup

Connect Azure AI Services models to [OpenCode](https://opencode.ai/) in minutes. Discovers your resources, configures the provider, and filters the model list to only what you've deployed.

## What it does

Your AI coding agent follows a 7-step workflow:

1. **Discover** — Finds AI Services resources across all your Azure subscriptions
2. **Match** — Maps your endpoint to the correct OpenCode provider (`azure-cognitive-services` or `azure`)
3. **Verify** — Smoke-tests the endpoint before configuring anything
4. **Auth** — Sets env var + `/connect` API key (stored securely in `auth.json`)
5. **Configure** — Writes `opencode.json` with `whitelist` filtering and `disabled_providers`
6. **Validate** — Checks quota and deployment status to catch 429s and 404s early
7. **Done** — Select your model with `/models`

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
├── SKILL.md                              # Main skill (workflow + config template)
└── references/
    ├── discovery-scripts.md              # Cross-subscription az CLI loops
    ├── verify-endpoint.md                # PowerShell + bash smoke tests
    ├── quota-validation.md               # Pre-flight capacity & quota checks
    └── troubleshooting.md                # Common errors + fixes
```

## Prerequisites

- Azure CLI authenticated (`az login`)
- OpenCode installed
- An Azure subscription with an AI Services or OpenAI resource that has deployed models

## Key features

| Feature | Details |
|---------|---------|
| **Cross-subscription discovery** | Loops through all subs to find AI resources |
| **Whitelist filtering** | Shows only deployed models in `/models` (via [undocumented whitelist](https://github.com/anomalyco/opencode/issues/9203)) |
| **Dual provider support** | Handles both `*.cognitiveservices.azure.com` and `*.openai.azure.com` |
| **Quota validation** | Catches exhausted quota before you hit 429s |
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
