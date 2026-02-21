# Contributing

## Running scripts locally

All commands must be run from **repo root**. No `cd scripts/` — relative paths in the scripts assume repo root as cwd.

### Bash (Linux / macOS / WSL)

```bash
# Does not require chmod +x — bash prefix is explicit
bash scripts/emit-opencode-azure-cogsvc-config.sh            # dry run
bash scripts/emit-opencode-azure-cogsvc-config.sh --apply    # apply
bash scripts/emit-opencode-azure-cogsvc-config.sh --smoke    # connectivity check only
bash scripts/test-invariants.sh                              # 15-invariant suite
```

### PowerShell (Windows)

Requires **PowerShell 5.1** (declared via `#Requires -Version 5.1`) or **pwsh 7+**.
File is saved as **UTF-8 with BOM** — do not re-save as UTF-8 without BOM or PS5.1
will misread non-ASCII characters.

```powershell
# Run from repo root in PowerShell
.\scripts\emit-opencode-azure-cogsvc-config.ps1              # dry run
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -Apply       # apply
.\scripts\emit-opencode-azure-cogsvc-config.ps1 -VerifyOnly  # connectivity check only
```

If you get `cannot be loaded because running scripts is disabled`:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Do not mix shells

- `.\scripts\foo.ps1` in Git Bash = broken path (`C:Usersfoo.ps1` without backslashes)
- `bash scripts\foo.sh` on vanilla CMD = broken
- Use the right shell for the right script. If in doubt: **bash for `.sh`, pwsh for `.ps1`**

---

## Running CI locally

```bash
# ShellCheck (requires shellcheck installed)
shellcheck --severity=warning --exclude=SC2034,SC1090 \
  scripts/emit-opencode-azure-cogsvc-config.sh \
  scripts/test-invariants.sh

# JSON validity
jq -e . references/models.dev.azure.json > /dev/null

# Full invariant suite
bash scripts/test-invariants.sh

# PowerShell parse check (run in PowerShell)
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  "scripts\emit-opencode-azure-cogsvc-config.ps1", [ref]$null, [ref]$errors) | Out-Null
$errors | Format-List Message, Extent
```

---

## Path rules in CI

Every workflow job sets:

```yaml
defaults:
  run:
    working-directory: ${{ github.workspace }}
```

Scripts are called as `bash scripts/foo.sh` (Linux) or via `$env:GITHUB_WORKSPACE` 
(Windows) — never with `cd` and never with `./` without `chmod +x`.

The first step in each job runs `pwd && ls -la` to confirm working directory.
If a script-not-found error appears, check that step's output first.

---

## Encoding rules for .ps1 files

- Save as **UTF-8 with BOM** (`EF BB BF` first three bytes)
- Use **ASCII-only** in string literals — no curly quotes, em-dashes, or box-drawing characters
- PS5.1 reads UTF-8-without-BOM as Windows-1252 (ACP); curly quote bytes `E2 80 9D`
  become mojibake that the lexer reads as a string terminator

To verify encoding:

```powershell
$bytes = [System.IO.File]::ReadAllBytes("scripts\emit-opencode-azure-cogsvc-config.ps1")
$bytes[0..2] -join ' '   # must be: 239 187 191
```

To re-save with BOM if accidentally stripped:

```powershell
$path = "scripts\emit-opencode-azure-cogsvc-config.ps1"
$txt = Get-Content $path -Raw
[System.IO.File]::WriteAllText($path, $txt, (New-Object System.Text.UTF8Encoding($true)))
```
