# SDL Audit Report — `azure-opencode-setup` v0.1.2

**Auditor:** SDL Enforcer (automated + manual review)
**Date:** 2026-02-22
**Scope:** Full repo audit against SDL Enforcer Prompt (Turn 0)
**Overall Risk Rating:** **HIGH** — 3 blocking findings, 5 warnings

---

## 1. Automated Gate Results

| #   | Gate                | Tool                    | Result   | Detail                                                  |
| --- | ------------------- | ----------------------- | -------- | ------------------------------------------------------- |
| 1   | Lint (all rules)    | `ruff`                  | **FAIL** | 61 violations (see §2)                                  |
| 2   | Type check (strict) | `mypy --strict`         | **PASS** | 0 issues in 8 files                                     |
| 3   | Type check (strict) | `pyright strict`        | **PASS** | 0 errors, 0 warnings                                    |
| 4   | SAST                | `bandit`                | **PASS** | 0 findings, 841 LOC scanned                             |
| 5   | Secret scanning     | `detect-secrets`        | **WARN** | 1 finding — false positive (see §3)                     |
| 6   | Dependency audit    | `pip-audit`             | **PASS** | 0 known vulnerabilities                                 |
| 7   | Tests + coverage    | `pytest`                | **PASS** | 104 passed, 97.40% branch coverage (≥95%)               |
| 8   | Shell lint          | `shellcheck`            | **PASS** | 0 warnings on both `.sh` files                          |
| 9   | PowerShell parse    | `[Parser]::ParseFile()` | **PASS** | 0 parse errors                                          |
| 10  | Script integrity    | `checksums.txt`         | **FAIL** | Both hashes stale (see §4)                              |
| 11  | SHA-pinned actions  | manual grep             | **PASS** | All 9 `uses:` entries are SHA-pinned                    |
| 12  | Heredoc in YAML     | manual grep             | **PASS** | `printf '%s\n'` used throughout (CONTRACT-03 compliant) |

---

## 2. `[SDL-BLOCK]` Findings — Must Fix Before Merge/Release

### BLOCK-01: `ruff` — 61 violations (gate §3a)

**Rule:** Ruff with `select = ["ALL"]` must report zero violations.

**Breakdown:**

| Category                                     | Count | Files         | Severity                                                                      |
| -------------------------------------------- | ----- | ------------- | ----------------------------------------------------------------------------- |
| `D107` — Missing `__init__` docstrings       | 5     | `errors.py`   | LOW (fix: add docstrings)                                                     |
| `N802` — Win32 API names not lowercase       | 6     | `io.py`       | LOW (suppress per-file; API names are normative)                              |
| `PLR0913` — Too many args in Win32 protocols | 2     | `io.py`       | LOW (suppress; mirrors Win32 API)                                             |
| `TRY003/EM101` — Exception message style     | 2     | `io.py`       | LOW (fix: assign to variable)                                                 |
| `B009` — `getattr` with constant attr        | 2     | `io.py`       | LOW (fix: use direct attribute access, or suppress — `windll` is conditional) |
| `E501` — Line too long                       | 1     | `merge.py:68` | LOW (fix: wrap line)                                                          |
| `D101/D102` — Missing test docstrings        | ~20   | `tests/`      | INFO (needs `per-file-ignores`)                                               |
| `S101` — assert in tests                     | ~18   | `tests/`      | INFO (needs `per-file-ignores`)                                               |
| `PLR2004` — Magic values in tests            | 3     | `tests/`      | INFO (needs `per-file-ignores`)                                               |

**Remediation:** Add `[tool.ruff.lint.per-file-ignores]` to `pyproject.toml`:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "D100", "D101", "D102", "D103", "D107", "PLR2004"]
"src/azure_opencode_setup/io.py" = ["N802", "PLR0913"]  # Win32 API protocol types
```

Then fix the remaining 5 source violations (D107 in errors.py, TRY003/EM101/B009 in io.py, E501 in merge.py).

---

### BLOCK-02: `checksums.txt` stale — script integrity unverifiable (Release §5)

**Rule:** `checksums.txt` SHA-256 hashes must match current script contents.

**Evidence:**

| Script                                  | `checksums.txt` hash | Computed hash (LF-normalized) |
| --------------------------------------- | -------------------- | ----------------------------- |
| `emit-opencode-azure-cogsvc-config.sh`  | `415ab8b...`         | `dec6e29...`                  |
| `emit-opencode-azure-cogsvc-config.ps1` | `e9b5347...`         | `0761148...`                  |

Git log shows scripts were modified after checksums were recorded:

- `checksums.txt` last updated at `7c8cc7d` (release/0.1.2)
- Scripts modified at `f85137b` ("wip: stabilize current scripts before python rewrite")

**Remediation:** Regenerate `checksums.txt` from the current script content. Also add a `.gitattributes` to force consistent line endings for `.sh` files (`eol=lf`) so checksums are reproducible cross-platform.

---

### BLOCK-03: CONTRACT-02 regression — PS1 paths contradict contract (SDL §2, Standing Order 7)

**Rule:** CONTRACT-02 states Windows paths use `%LOCALAPPDATA%` (auth) and `%APPDATA%` (config). Modifying a contract requires updating the contract doc, the test, and the enforcer prompt.

**Evidence:**

The PS1 script currently uses:

```powershell
# auth — CONTRACT-02 says: $env:LOCALAPPDATA\opencode\auth.json
$authPath = Join-Path $HOME ".local\share\opencode\auth.json"

# config — CONTRACT-02 says: $env:APPDATA\opencode\opencode.json
[string]$ConfigPath = (Join-Path $HOME ".config\opencode\opencode.json")
```

The Python `paths.py` also uses `~/.local/share/...` and `~/.config/...` with the docstring "verified via Context7".

The PS1 help text at line 21 even says `Default: %APPDATA%\opencode\opencode.json` but the code default is `$HOME\.config\...`.

**Impact:**

- INV-07 (`grep -qE 'LOCALAPPDATA.*opencode'`) would **FAIL** — 0 occurrences of `LOCALAPPDATA`
- INV-07b technically passes but only because it matches the stale documentation text, not actual code
- If CONTRACT-02 is correct, files are being written to paths OpenCode never reads on Windows → **silent auth failure**
- If `paths.py` is correct, CONTRACT-02 is stale and must be updated per Standing Order 7

**Remediation:** Resolve the contradiction:

1. Re-verify against OpenCode source which Windows path is actually used
2. Update whichever is wrong: either CONTRACT-02 + INV-07/07b tests, or `paths.py` + PS1 + Python tests
3. Update the PS1 docstring to match either way

---

## 3. `[SDL-WARN]` Findings — Should Fix

### WARN-01: `detect-secrets` — false positive on content_hash (gate §4)

**Finding:** `references/models.dev.azure.json:217` flagged as "Hex High Entropy String" — the `_meta.content_hash` field (`eb3ba50387b076dc`).

**Assessment:** This is a content-integrity hash, not a secret. The value is a truncated SHA-256 of the snapshot data.

**Remediation:** Create a `.secrets.baseline` file to mark this as a known false positive, or add an inline `# pragma: allowlist secret` equivalent in the JSON (not practical for JSON). Recommend a baseline file:

```bash
uv run detect-secrets scan --baseline .secrets.baseline
```

---

### WARN-02: Non-atomic `opencode.json` write in bash script (Standing Order 4)

**Rule:** All writes to `auth.json` and `opencode.json` must use atomic write (tmpfile → fsync → replace).

**Evidence:** `emit-opencode-azure-cogsvc-config.sh` line ~275:

```bash
echo "$MERGED" > "$CONFIG_PATH"
```

This is a direct redirect, not atomic. If interrupted, `opencode.json` could be corrupted/truncated.

`auth.json` correctly uses `> "${AUTH_PATH}.tmp"` then `mv`.

**Remediation:** Apply the same tmp+mv pattern:

```bash
echo "$MERGED" > "${CONFIG_PATH}.tmp"
mv "${CONFIG_PATH}.tmp" "$CONFIG_PATH"
```

---

### WARN-03: Non-atomic writes in PS1 script (Standing Order 4)

**Rule:** Same as WARN-02.

**Evidence:** Both files written non-atomically in `emit-opencode-azure-cogsvc-config.ps1`:

```powershell
# opencode.json (line ~320)
[System.IO.File]::WriteAllText($ConfigPath, ...)

# auth.json (line ~340)
[System.IO.File]::WriteAllText($authPath, ...)
```

Neither uses a temp-file + rename pattern.

**Remediation:** Write to `$ConfigPath.tmp` then `Move-Item -Force`, same for auth.

---

### WARN-04: Backup files on Windows lack ACL restriction (Standing Order 5)

**Rule:** Security properties must hold on both POSIX and Windows.

**Evidence:** `locking.py` `backup_file()`:

```python
shutil.copy2(str(path), str(backup_path))
if sys.platform != "win32":
    backup_path.chmod(0o600)
```

On POSIX, backup gets `chmod 0o600`. On Windows, no ACL restriction is applied. `shutil.copy2` preserves stat metadata but does **not** preserve Windows DACLs. A backup of `auth.json` (containing API keys) could be readable by other local users.

**Remediation:** Call `restrict_permissions(backup_path)` on Windows as well, or add a Windows-specific ACL copy.

---

### WARN-05: Missing `.gitattributes` — cross-platform reproducibility risk

**Finding:** No `.gitattributes` file exists. Line ending behavior depends entirely on each developer's `core.autocrlf` setting.

**Impact:**

- `checksums.txt` verification fails cross-platform (LF vs CRLF)
- UTF-8 BOM requirement for `.ps1` files (CONTRIBUTING.md) isn't enforced by git
- Shell scripts could get CRLF on Windows checkout, causing `\r` in bash

**Remediation:**

```gitattributes
# Enforce LF for shell scripts
*.sh text eol=lf
# Enforce UTF-8 with BOM for PS 5.1 compat
*.ps1 text working-tree-encoding=utf-8-bom
# JSON always LF
*.json text eol=lf
```

---

## 4. Verification Checklist (per-PR template from SDL Enforcer)

```
[x] bandit: zero findings
[~] detect-secrets: 1 false positive (content_hash in vendored JSON) — needs baseline
[x] pip-audit: zero known vulnerabilities
[x] mypy + pyright: zero errors
[ ] ruff: 61 violations — NEEDS per-file-ignores + 5 source fixes
[x] shellcheck: zero warnings (severity≥warning)
[x] pytest: ≥95% branch coverage (97.40%), all 104 tests pass
[?] test-invariants.sh: INV-07 would FAIL on current PS1 (LOCALAPPDATA missing)
[x] No SHA-unpinned GitHub Actions
[x] No new CLI arguments that accept secrets as values
[ ] No weakening of file permission restrictions — WARN-04 (backup ACL gap)
[ ] No CONTRACT-* regression without documented replacement — BLOCK-03
```

---

## 5. SDL Phase Summary

| Phase              | Status    | Key Issues                                                                                                                                                   |
| ------------------ | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Requirements**   | PASS      | R-01 through R-04 all hold. No new attack surface, no new secret flows, least privilege maintained, no telemetry.                                            |
| **Design**         | **BLOCK** | Threat table mitigation for Tampering (CONTRACT-04) is intact in Python code but violated in shell scripts (non-atomic writes). CONTRACT-02 path regression. |
| **Implementation** | **BLOCK** | ruff violations (fixable). Non-atomic writes in scripts. Missing `.gitattributes`.                                                                           |
| **Verification**   | **BLOCK** | checksums.txt stale. INV-07 would fail. detect-secrets needs baseline.                                                                                       |
| **Release**        | **BLOCK** | Cannot release until checksums updated, ruff green, contract contradiction resolved.                                                                         |

---

## 6. Recommended Fix Priority

| Priority | Finding                                                       | Effort                                         |
| -------- | ------------------------------------------------------------- | ---------------------------------------------- |
| **P0**   | BLOCK-03: Resolve CONTRACT-02 vs paths.py contradiction       | Medium — requires OpenCode source verification |
| **P0**   | BLOCK-02: Regenerate checksums.txt + add .gitattributes       | Low                                            |
| **P0**   | BLOCK-01: Add ruff per-file-ignores + fix 5 source violations | Low                                            |
| **P1**   | WARN-02/03: Atomic writes in shell scripts                    | Low                                            |
| **P1**   | WARN-04: Windows backup ACL restriction                       | Low                                            |
| **P1**   | WARN-01: detect-secrets baseline file                         | Low                                            |
| **P2**   | WARN-05: .gitattributes for line ending consistency           | Low                                            |

---

_Report generated against SDL Enforcer Prompt v0.1.2 — 2026-02-22._
