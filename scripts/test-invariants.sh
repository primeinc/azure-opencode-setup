#!/usr/bin/env bash
# test-invariants.sh — Assert security and correctness contracts for azure-opencode-setup.
#
# These assert external contracts we depend on. A failure means the contract has drifted
# and the scripts must be reviewed. Run in CI on every push.
#
# Contracts asserted:
#   INV-01  models.dev Azure model IDs are lowercase       (whitelist lowercasing is correct)
#   INV-02  models.dev Azure env var names match scripts   (AZURE_RESOURCE_NAME etc. unchanged)
#   INV-03  properties.endpoint trailing-slash (live az)   (trailing-slash guard tracks drift)
#   INV-04  No eval usage in .sh                           (SEC-02 regression guard)
#   INV-05  No sed variable-in-replacement in .sh          (SEC-01 regression guard)
#   INV-06  No double /openai/ in endpoint concat          (ARM vs SDK path confusion guard)
#   INV-07  .ps1 auth.json uses LOCALAPPDATA               (xdg-basedir Windows path correct)
#   INV-07b .ps1 config uses APPDATA                       (xdg-basedir Windows path correct)
#   INV-08  .sh sets chmod 600 on auth.json                (Bun mode:0o600 is Unix-only)
#
# INV-01 and INV-02 assert against references/models.dev.azure.json (vendored snapshot).
# This makes PR CI deterministic. The live-network refresh job is in:
#   .github/workflows/refresh-models-snapshot.yml
#
# Environment variables:
#   INVARIANTS_REQUIRE_NETWORK=1  — treat network unavailability as FAIL (default: SKIP)
#
# Exit codes: 0 = all asserted invariants pass, 1 = at least one FAIL

# Accumulate failures: do NOT use set -e globally because (( expr )) returns
# exit 1 when the expression evaluates to zero (e.g. FAIL++ when FAIL=0).
# We use set -uo pipefail to catch unbound vars and broken pipes, but handle
# arithmetic manually.
set -uo pipefail

PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SH_SCRIPT="$SCRIPT_DIR/emit-opencode-azure-cogsvc-config.sh"
PS1_SCRIPT="$SCRIPT_DIR/emit-opencode-azure-cogsvc-config.ps1"
SNAPSHOT="$REPO_ROOT/references/models.dev.azure.json"
INVARIANTS_REQUIRE_NETWORK="${INVARIANTS_REQUIRE_NETWORK:-0}"

# ── Helpers ───────────────────────────────────────────────────────────────────

pass() {
  echo "  PASS  $1"
  PASS=$(( PASS + 1 ))
}

fail() {
  echo "  FAIL  $1"
  echo "        $2"
  FAIL=$(( FAIL + 1 ))
}

skip() {
  echo "  SKIP  $1"
}

# ── Snapshot presence check ───────────────────────────────────────────────────

if [[ ! -f "$SNAPSHOT" ]]; then
  echo "ERROR: Snapshot not found: $SNAPSHOT"
  echo "       Run: scripts/refresh-models-snapshot.sh to generate it."
  exit 1
fi

# ── INV-01: All Azure model IDs in snapshot are lowercase ────────────────────
# Contract: models.dev emits lowercase-only model ID keys for Azure providers.
# OpenCode whitelist compare is case-sensitive (provider.ts Array.includes()).
# Scripts apply ascii_downcase / .ToLower() so IDs match. If models.dev drifts
# to mixed-case, lowercasing would SILENTLY block those models from the whitelist.
# Asserted against vendored snapshot; live drift caught by refresh-models-snapshot.yml.

echo ""
echo "INV-01  models.dev Azure model IDs are lowercase (snapshot)"

for PROVIDER_ID in azure "azure-cognitive-services"; do
  MODELS=$(jq -r --arg p "$PROVIDER_ID" '.[$p].model_ids // [] | .[]' "$SNAPSHOT")

  if [[ -z "$MODELS" ]]; then
    fail "INV-01[$PROVIDER_ID]" "Provider not found in snapshot: $SNAPSHOT"
    continue
  fi

  MIXED=$(echo "$MODELS" | grep -E '[A-Z]' || true)
  if [[ -n "$MIXED" ]]; then
    fail "INV-01[$PROVIDER_ID]" \
      "Mixed-case IDs — .ToLower() would silently break whitelist: $(echo "$MIXED" | head -5 | tr '\n' ' ')"
  else
    COUNT=$(echo "$MODELS" | wc -l | tr -d ' ')
    pass "INV-01[$PROVIDER_ID]  $COUNT model IDs all lowercase"
  fi
done

# ── INV-02: models.dev env var names match scripts ───────────────────────────
# Contract: models.dev "env" arrays contain the env var names the scripts set.
# If models.dev renames them (e.g. AZURE_API_KEY → AZURE_OPENAI_API_KEY),
# /connect breaks silently. Asserted against vendored snapshot.

echo ""
echo "INV-02  models.dev Azure env var names match scripts (snapshot)"

check_env() {
  local PROVIDER_ID="$1"
  local EXPECTED="$2"
  local FOUND
  FOUND=$(jq -r --arg p "$PROVIDER_ID" --arg e "$EXPECTED" \
    '.[$p].env // [] | map(select(. == $e)) | length' "$SNAPSHOT")
  if [[ "$FOUND" -gt 0 ]]; then
    pass "INV-02[$PROVIDER_ID]  $EXPECTED present"
  else
    local ACTUAL
    ACTUAL=$(jq -r --arg p "$PROVIDER_ID" '.[$p].env // [] | join(", ")' "$SNAPSHOT")
    fail "INV-02[$PROVIDER_ID]" \
      "$EXPECTED not in snapshot env. Actual: $ACTUAL — run refresh-models-snapshot.yml"
  fi
}

check_env "azure"                     "AZURE_RESOURCE_NAME"
check_env "azure"                     "AZURE_API_KEY"
check_env "azure-cognitive-services"  "AZURE_COGNITIVE_SERVICES_RESOURCE_NAME"
check_env "azure-cognitive-services"  "AZURE_COGNITIVE_SERVICES_API_KEY"

# ── INV-03: Sample endpoints end with / (requires live az) ───────────────────
# Contract: ARM properties.endpoint ends with /. Our trailing-slash guard is
# defensive — tracks whether Azure changes the format. Requires az login.

echo ""
echo "INV-03  properties.endpoint trailing-slash (requires az login)"

if command -v az &>/dev/null && az account show &>/dev/null 2>&1; then
  SAMPLE=$(az cognitiveservices account list -o json 2>/dev/null \
    | jq -r '.[0].properties.endpoint // empty' 2>/dev/null || true)
  if [[ -z "$SAMPLE" ]]; then
    skip "INV-03  no Cognitive Services accounts in current subscription"
  elif [[ "$SAMPLE" == */ ]]; then
    pass "INV-03  endpoint ends with /: $SAMPLE"
  else
    fail "INV-03" \
      "endpoint does NOT end with /: $SAMPLE — guard is now required not defensive"
  fi
else
  skip "INV-03  az not available or not logged in"
fi

# ── INV-04: No eval in .sh ────────────────────────────────────────────────────
# Contract: eval removed per SEC-02. Any reintroduction is a shell injection vector.

echo ""
echo "INV-04  No eval usage in .sh"

EVAL_HITS=$(grep -n '\beval\b' "$SH_SCRIPT" | grep -v '^\s*#' || true)
if [[ -n "$EVAL_HITS" ]]; then
  fail "INV-04" "eval found in $(basename "$SH_SCRIPT"): $EVAL_HITS"
else
  pass "INV-04  no eval in $(basename "$SH_SCRIPT")"
fi

# ── INV-05: No sed replacement with variable in RHS ──────────────────────────
# Contract: sed injection fixed per SEC-01. Pattern: sed 's/.../$VAR/' where
# the variable is in the replacement position is the injection site.

echo ""
echo "INV-05  No sed variable-in-replacement in .sh"

SED_HITS=$(grep -nE "sed\s+-i[^ ]*\s+[\"']s[|/][^|/]+[|/]\\\$[A-Z_]" "$SH_SCRIPT" || true)
if [[ -n "$SED_HITS" ]]; then
  fail "INV-05" "sed injection pattern in replacement RHS: $SED_HITS"
else
  pass "INV-05  no sed variable-in-replacement found"
fi

# ── INV-06: No double /openai/ in endpoint concatenation ─────────────────────
# Contract: ARM properties.endpoint = https://foo.azure.com/ (no /openai/ suffix).
# SDK baseURL adds /openai internally. Verification curl uses ${ENDPOINT}openai/...
# which is correct. This guards against accidentally writing /openai/openai/.

echo ""
echo "INV-06  No double /openai/ in endpoint concat"

for SCRIPT in "$SH_SCRIPT" "$PS1_SCRIPT"; do
  DOUBLE=$(grep -n 'openai.*openai\|openai/openai' "$SCRIPT" || true)
  if [[ -n "$DOUBLE" ]]; then
    fail "INV-06[$(basename "$SCRIPT")]" "Double /openai/ path: $DOUBLE"
  else
    pass "INV-06[$(basename "$SCRIPT")]  no double /openai/"
  fi
done

# ── INV-07: .ps1 uses correct Windows XDG paths ──────────────────────────────
# Contract: xdg-basedir on Windows: data → %LOCALAPPDATA%, config → %APPDATA%.
# Using ~/.local/share or ~/.config would silently write to paths OpenCode never reads.

echo ""
echo "INV-07  .ps1 uses correct Windows XDG paths"

if grep -qE 'LOCALAPPDATA.*opencode' "$PS1_SCRIPT"; then
  pass "INV-07   LOCALAPPDATA auth path in $(basename "$PS1_SCRIPT")"
else
  fail "INV-07" "LOCALAPPDATA not found for auth.json — may have reverted to ~/.local/share"
fi

if grep -qE 'env:APPDATA.*opencode|APPDATA.*opencode' "$PS1_SCRIPT"; then
  pass "INV-07b  APPDATA config path in $(basename "$PS1_SCRIPT")"
else
  fail "INV-07b" "APPDATA not found for opencode.json — may have reverted to ~/.config"
fi

# ── INV-08: .sh sets chmod 600 on auth.json ──────────────────────────────────
# Contract: Bun.write mode:0o600 is Unix-only; .sh must explicitly chmod 600.

echo ""
echo "INV-08  .sh sets chmod 600 on auth.json"

if grep -qE 'chmod\s+600' "$SH_SCRIPT"; then
  pass "INV-08  chmod 600 present in $(basename "$SH_SCRIPT")"
else
  fail "INV-08" "chmod 600 not found for auth.json in $(basename "$SH_SCRIPT")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
echo "─────────────────────────────────────"

if [[ "$FAIL" -gt 0 ]]; then
  echo "FAIL — $FAIL invariant(s) broken. Review findings above."
  exit 1
else
  echo "PASS — all invariants hold."
  exit 0
fi
