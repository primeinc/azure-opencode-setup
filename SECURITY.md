# Security Policy

This repository contains automation scripts that discover Azure AI resources and write local OpenCode configuration/auth files.

## Security model

- Default mode is non-persistent: scripts do not modify shell profiles or User env vars unless explicitly requested.
- API keys are stored in OpenCode `auth.json` (`type: "api", key: "..."`) as required by OpenCode auth schema.
- Endpoint validation calls are sent only to the selected Azure endpoint and deployment.

## Safe defaults

- `--apply` / `-Apply` writes config + auth only.
- Env var writes are opt-in:
  - bash: `--set-env` (session), `--persist-env` (rc file)
  - pwsh: `-SetEnv` (session), `-PersistEnv` (User scope)
- `--smoke` / `-VerifyOnly` performs read-only discovery + verification, no file writes.

## Known risk boundaries

- Local secret at rest: API key is written to local `auth.json` by design.
- Azure CLI output is untrusted input; scripts constrain usage to expected fields and encode outputs before file writes.
- `npx skills add` executes remote package code; prefer pinned/manual install in high-assurance environments.

## Reporting

Open a GitHub issue with:

- repro command
- OS + shell + PowerShell version
- script output (redacted)
- expected vs actual behavior
