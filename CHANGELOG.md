# Changelog

All notable changes to this project will be documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [0.1.0] — 2026-02-21

### Added

- `scripts/emit-opencode-azure-cogsvc-config.sh` — bash config emitter for Azure AI Services + OpenCode
- `scripts/emit-opencode-azure-cogsvc-config.ps1` — PowerShell equivalent for Windows
- `--smoke` / `-VerifyOnly` mode: read-only Azure validation, no file writes, exit code signals pass/fail
- `scripts/test-invariants.sh` — 15 invariants asserting security contracts and source-verified assumptions
- `references/models.dev.azure.json` — vendored snapshot of models.dev Azure provider slices with content_hash
- `references/contracts.md` — named contracts with citations (whitelist casing, Windows paths, ACL method, YAML heredoc constraint)
- `references/config-template.md` — extracted config template, whitelist rules, self-check scripts
- `.github/workflows/validate.yml` — CI: skill-spec, invariants (snapshot-based, deterministic), invariants-live (non-blocking), shellcheck
- `.github/workflows/refresh-models-snapshot.yml` — weekly drift detection; opens PR if models.dev changes
- `.github/workflows/integration-smoke.yml` — manual Azure end-to-end smoke; self-skips if OIDC secrets absent

### Fixed (security — source-verified against MS Learn + OpenCode source)

- **SEC-01/02**: Replaced `eval "$EXPORT_LINE"` and `sed` injection with `printf '%q'` + `grep -v` + direct `export`
- **SEC-03**: Added `ResetAccessRule` + `SetAccessRuleProtection` ACL block to `.ps1`; matches MS Learn `FileSystemSecurity` spec exactly
- **SEC-04**: Updated `api-version` from `2024-12-01-preview` to `2024-10-21` (current GA; confirmed via MS Learn API lifecycle page)
- **OC-01**: Fixed Windows `auth.json` path from `~/.local/share/opencode/` to `$env:LOCALAPPDATA\opencode\` (source: OpenCode `global/index.ts` via `xdg-basedir`)
- **OC-02**: Fixed Windows `opencode.json` path from `~/.config/opencode/` to `$env:APPDATA\opencode\` (same source)
- **ARM-01**: Added null guard for `properties.model.version` (ARM schema: optional field; confirmed via REST API reference)
- **ARM-02**: Added endpoint trailing-slash guard in both scripts (ARM `properties.endpoint` has no trailing-slash contract)

### Changed

- SKILL.md: moved `USE FOR` / `DO NOT USE FOR` from frontmatter `description` to body `## When to Use` section
- SKILL.md: fixed all reference links from backtick code-spans to `[text](path)` markdown hyperlinks (JIT loading requires hyperlink syntax)
- SKILL.md: removed `[OPENCODE-NORMATIVE]` and `[PROPOSED]` inline annotations

### Validated against first-party sources

- Azure CLI: `az cognitiveservices account deployment list`, `keys list`, `account show` — all confirmed GA
- Azure REST: deployment object schema, `properties.model.name/version` optionality, error response shape
- models.dev: all Azure provider model IDs confirmed lowercase; env var names confirmed
- OpenCode source (`provider.ts`, `auth/index.ts`, `global/index.ts`, `config/config.ts`): provider IDs, auth schema, config paths, whitelist comparison semantics

---

## [Unreleased]

_Nothing yet._
