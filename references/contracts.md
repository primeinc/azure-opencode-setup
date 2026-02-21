# Contracts

Named invariants that must hold across refactors. Each has a source citation,
an assertion location, and a breakage consequence. Before changing any of the
behaviours below, read the contract and update the test — don't just "fix" the
test to match the new behaviour without understanding why the contract exists.

---

## CONTRACT-01: Whitelist values must be lowercase

**Rule:** Model IDs written to `opencode.json` provider whitelist must be
lowercase.

**Why:** OpenCode's whitelist check is `Array.prototype.includes()` — case-
sensitive, no normalization (source: `provider.ts:993`). models.dev emits all
Azure model IDs in lowercase (verified against `models.dev/api.json` on
2026-02-21; all 189 azure + azure-cognitive-services model keys are lowercase).
Writing a mixed-case deployment name (e.g. `GPT-4o`) would silently block that
model from appearing in OpenCode.

**Source:** `C:\Users\will\dev\refs\opencode\packages\opencode\src\provider\provider.ts:993`
and `https://models.dev/api.json` (vendored in `references/models.dev.azure.json`).

**Assertion:** `scripts/test-invariants.sh` INV-02 (env var names), INV-01 (all
model IDs lowercase in snapshot). Scripts use `.ToLower()` / `ascii_downcase`.

**If models.dev ever changes casing:** INV-01 will fail on the next scheduled
refresh (`refresh-models-snapshot.yml`). The PR it opens will contain the drift.
At that point: update this contract, update the scripts, merge the PR.

---

## CONTRACT-02: Windows paths via xdg-basedir (not Unix paths)

**Rule:** On Windows, OpenCode reads:
- `auth.json` from `%LOCALAPPDATA%\opencode\auth.json`
- `opencode.json` from `%APPDATA%\opencode\opencode.json`

**Not** `~/.local/share/opencode/` or `~/.config/opencode/` (those are Unix
paths; OpenCode on Windows never reads them).

**Why:** OpenCode uses the `xdg-basedir` npm package. On Windows, xdg-basedir
resolves `data` → `%LOCALAPPDATA%` and `config` → `%APPDATA%`
(source: `global/index.ts:8,10` in OpenCode source).

**Source:** `C:\Users\will\dev\refs\opencode\packages\opencode\src\global\index.ts:8-10`

**Assertion:** `scripts/test-invariants.sh` INV-07 / INV-07b.

**Breakage consequence:** Writing to the wrong path silently succeeds — auth
appears saved, OpenCode finds no auth, `/connect` fails with no useful error.

---

## CONTRACT-03: YAML run blocks cannot contain heredocs

**Rule:** Do not use `<<EOF ... EOF` inside GitHub Actions `run: |` blocks.
Use `printf '%s\n' ... > /tmp/file.ext` instead.

**Why:** Two incompatible constraints:
1. YAML block scalars (§8.1.1.1): every non-empty line must be indented at
   or above the scalar's content indentation level. A column-0 `EOF` terminator
   is a YAML parse error inside any indented `run:` block.
2. Bash heredoc grammar: the `EOF` terminator must appear at column 0 (or
   tab-stripped with `<<-`).

These cannot be simultaneously satisfied in a standard `run: |` block.
`printf '%s\n' ... > /tmp/file` is POSIX, requires no special indentation,
and works identically under `sh` and `bash`.

**Source:** YAML spec 1.2.2 §8.1.1.1 (block indentation indicator);
GitHub Actions docs (`jobs.<job_id>.steps[*].run`).

**Assertion:** Workflow files in `.github/workflows/` use `printf` for multi-
line file generation. Checked by code review — no automated invariant (grep
for `<<EOF` in workflow files would be the right lint).

---

## CONTRACT-04: ACL hardening uses ResetAccessRule, not RemoveAccessRule loop

**Rule:** The `auth.json` file on Windows must be restricted to the current
user only (chmod 600 equivalent). The implementation must use:
1. `$acl.SetAccessRuleProtection($true, $false)` — disables inheritance,
   removes inherited ACEs.
2. `$acl.ResetAccessRule($rule)` — atomically clears the entire DACL and
   adds exactly one allow ACE for the current user.

**Not** `$acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) }` — this
modifies a collection during enumeration and `RemoveAccessRule` matches by
SID+mask, not "everything". It will silently leave ACEs for SYSTEM or
Administrators if they were explicit (not inherited).

**Why:** `ResetAccessRule` doc: "Removes all access rules in the DACL
associated with this object and then adds the specified access rule."
(source: MS Learn `CommonObjectSecurity.ResetAccessRule`).
`SetAccessRuleProtection($true, $false)` only removes *inherited* ACEs —
explicit ACEs survive it unchanged.

**Source:** `https://learn.microsoft.com/dotnet/api/system.security.accesscontrol.commonobjectsecurity.resetaccessrule`
and `https://learn.microsoft.com/dotnet/api/system.security.accesscontrol.objectsecurity.setaccessruleprotection`

**Assertion:** `scripts/test-invariants.sh` INV-08 (proximity check: chmod 600
adjacent to auth write in .sh; ResetAccessRule + SetAccessRuleProtection in
.ps1).
