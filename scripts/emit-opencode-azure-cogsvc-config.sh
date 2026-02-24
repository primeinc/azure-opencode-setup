#!/usr/bin/env bash
# emit-opencode-azure-cogsvc-config.sh
# Discovers Azure AI Services deployments and emits/applies an opencode.json provider block.
# All parameters optional. With zero args, scans all subscriptions and auto-picks best resource.
#
# Requirements: az (authenticated), jq
# Usage:
#   ./emit-opencode-azure-cogsvc-config.sh                                      # full auto, dry run
#   ./emit-opencode-azure-cogsvc-config.sh --apply                              # full auto, apply (no env writes)
#   ./emit-opencode-azure-cogsvc-config.sh --apply --set-env                    # also set env in current shell
#   ./emit-opencode-azure-cogsvc-config.sh --apply --persist-env                # persist env to ~/.bashrc or ~/.zshrc
#   ./emit-opencode-azure-cogsvc-config.sh --subscription <id> --resource <name>
#   ./emit-opencode-azure-cogsvc-config.sh --subscription <id> --apply
set -euo pipefail

SUB="" RES="" RG="" APPLY=false SMOKE=false SET_ENV=false PERSIST_ENV=false
CONFIG_PATH="${HOME}/.config/opencode/opencode.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUB="$2"; shift 2;;
    --resource)     RES="$2"; shift 2;;
    --rg)           RG="$2";  shift 2;;
    --apply)        APPLY=true; shift;;
    --config)       CONFIG_PATH="$2"; shift 2;;
    --smoke)        SMOKE=true; shift;;
    --set-env)      SET_ENV=true; shift;;
    --persist-env)  SET_ENV=true; PERSIST_ENV=true; shift;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

# ── Step 1: Find subscription ──────────────────────────────────────────────────
if [[ -z "$SUB" ]]; then
  echo "Scanning all subscriptions for AI resources..." >&2
  BEST_COUNT=0
  while IFS=$'\t' read -r sub_id sub_name; do
    sub_id=${sub_id//$'\r'/}
    sub_name=${sub_name//$'\r'/}
    while IFS=$'\t' read -r name rg; do
      name=${name//$'\r'/}
      rg=${rg//$'\r'/}
      count=$(az cognitiveservices account deployment list \
        --subscription "$sub_id" -g "$rg" -n "$name" -o json 2>/dev/null | jq 'length' || echo 0)
      echo "  $sub_name / $name ($rg): $count deployments" >&2
      if (( count > BEST_COUNT )); then
        BEST_COUNT=$count; SUB="$sub_id"; RES="$name"; RG="$rg"
      fi
    done < <(az cognitiveservices account list --subscription "$sub_id" \
      --query "[?kind=='AIServices' || kind=='OpenAI'].[name, resourceGroup]" -o tsv 2>/dev/null)
  done < <(az account list --query "[].[id, name]" -o tsv)

  [[ -z "$SUB" ]] && { echo "ERROR: No AIServices or OpenAI resources found in any subscription" >&2; exit 3; }
  echo "Selected: $RES ($BEST_COUNT deployments)" >&2
fi

az account set --subscription "$SUB" >/dev/null

# ── Step 2: Find resource (if subscription given but resource not) ─────────────
if [[ -z "$RES" ]]; then
  echo "Scanning subscription for AI resources..." >&2
  BEST_COUNT=0
  while IFS=$'\t' read -r name rg; do
    name=${name//$'\r'/}
    rg=${rg//$'\r'/}
    count=$(az cognitiveservices account deployment list -g "$rg" -n "$name" -o json 2>/dev/null | jq 'length' || echo 0)
    echo "  $name ($rg): $count deployments" >&2
    if (( count > BEST_COUNT )); then
      BEST_COUNT=$count; RES="$name"; RG="$rg"
    fi
  done < <(az cognitiveservices account list \
    --query "[?kind=='AIServices' || kind=='OpenAI'].[name, resourceGroup]" -o tsv)
  [[ -z "$RES" ]] && { echo "ERROR: No AIServices or OpenAI resources found" >&2; exit 3; }
  echo "Selected: $RES ($BEST_COUNT deployments)" >&2
fi

# ── Step 3: Resolve resource group ────────────────────────────────────────────
if [[ -z "$RG" ]]; then
  RG=$(az resource list --name "$RES" --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[0].resourceGroup" -o tsv)
fi
[[ -z "$RG" ]] && { echo "ERROR: Could not find resource group for '$RES'" >&2; exit 3; }

# ── Step 4: Get endpoint + determine provider [MICROSOFT-NORMATIVE] ──────────
ENDPOINT=$(az cognitiveservices account show -g "$RG" -n "$RES" --query "properties.endpoint" -o tsv)
[[ -z "$ENDPOINT" ]] && { echo "ERROR: No endpoint for $RES" >&2; exit 4; }
# ARM spec: properties.endpoint may or may not include trailing slash — normalise
[[ "$ENDPOINT" != */ ]] && ENDPOINT="${ENDPOINT}/"

if echo "$ENDPOINT" | grep -q 'cognitiveservices.azure.com'; then
  PROVIDER="azure-cognitive-services"
  ENV_VAR="AZURE_COGNITIVE_SERVICES_RESOURCE_NAME"
  DISABLE="azure"
elif echo "$ENDPOINT" | grep -q 'openai.azure.com'; then
  PROVIDER="azure"
  ENV_VAR="AZURE_RESOURCE_NAME"
  DISABLE="azure-cognitive-services"
else
  echo "ERROR: Unrecognized endpoint pattern: $ENDPOINT" >&2; exit 5
fi

# ── Step 5: List deployments [MICROSOFT-NORMATIVE: deployment name is truth] ──
DEPLOY_JSON=$(az cognitiveservices account deployment list -g "$RG" -n "$RES" -o json)
DEPLOY_COUNT=$(echo "$DEPLOY_JSON" | jq 'length')
(( DEPLOY_COUNT == 0 )) && { echo "ERROR: No deployments on $RES" >&2; exit 4; }

echo "" >&2
echo "Deployments on $RES:" >&2
echo "$DEPLOY_JSON" | jq -r '.[] | "  \(.name)" + (if .properties.model.name != null and ((.name | ascii_downcase) != (.properties.model.name | ascii_downcase)) then " (model: \(.properties.model.name))" else "" end)' >&2

# ── Step 6: Build whitelist + models block ────────────────────────────────────
# LOWERCASE CONTRACT: OpenCode's whitelist check (provider.ts) uses
# Array.includes() — case-sensitive, no normalization. models.dev emits all
# Azure model IDs in lowercase (gpt-4o, o1, phi-4, etc.). azure deployment
# names are user-defined and may be mixed-case. ascii_downcase normalizes both
# so whitelist entries always match what OpenCode looks up.
# Invariant asserted in: scripts/test-invariants.sh INV-01 + INV-02.
# If INV-01 ever fails (models.dev drifts to mixed-case), revisit this logic.
# ARM schema: properties.model.name and .version are optional (auto-versioning).
# Use // empty to drop nulls rather than emitting the string "null".
WHITELIST=$(echo "$DEPLOY_JSON" | jq -r '
  [.[] | .name, (.properties.model.name // empty)]
  | map(ascii_downcase)
  | unique
  | sort
')

CUSTOM_MODELS=$(echo "$DEPLOY_JSON" | jq '
  [.[] | select(.properties.model.name != null)
       | select((.name | ascii_downcase) != (.properties.model.name | ascii_downcase))
       | select(.properties.model.name | test("^(gpt|o[0-9]|text-)") | not)]
  | if length > 0 then
      reduce .[] as $d ({}; .[$d.name | ascii_downcase] = {"name": "\($d.properties.model.name) (Azure)"})
    else {} end
')

# ── Step 7: Verify endpoint ──────────────────────────────────────────────────
API_KEY=$(az cognitiveservices account keys list -g "$RG" -n "$RES" --query "key1" -o tsv)
TEST_DEPLOY=$(echo "$DEPLOY_JSON" | jq -r '[.[] | select(.name | test("^gpt"))][0].name // .[0].name')

echo "" >&2
echo "Verifying endpoint with deployment '$TEST_DEPLOY'..." >&2
VERIFY_URL="${ENDPOINT}openai/deployments/${TEST_DEPLOY}/chat/completions?api-version=2024-10-21"
# Pass API key via temp --config file to avoid exposing it in process list.
# Process substitution (<(...)) is not reliable on all bash/curl combinations.
VERIFY_CFG=$(mktemp)
chmod 600 "$VERIFY_CFG"
printf 'header = "api-key: %s"\n' "$API_KEY" > "$VERIFY_CFG"
trap 'rm -f "$VERIFY_CFG"' EXIT
VERIFY_RESP=$(curl -sS -w "\n%{http_code}" "$VERIFY_URL" \
  --config "$VERIFY_CFG" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say ok"}],"max_tokens":5}' 2>&1)
rm -f "$VERIFY_CFG"
trap - EXIT
HTTP_CODE=$(echo "$VERIFY_RESP" | tail -1)
BODY=$(echo "$VERIFY_RESP" | sed '$d')
if [[ "$HTTP_CODE" == "200" ]]; then
  echo "Endpoint verified (HTTP 200)" >&2
else
  echo "WARNING: Endpoint returned HTTP $HTTP_CODE" >&2
  # Show Azure error message if present (strip API key from any error output)
  ERR_MSG=$(echo "$BODY" | jq -r '.error.message // empty' 2>/dev/null)
  [[ -n "$ERR_MSG" ]] && echo "  Error: $ERR_MSG" >&2
  echo "  Config will still be generated. Check troubleshooting docs." >&2
fi

# ── Step 8: Build output ─────────────────────────────────────────────────────
BASE_URL="${ENDPOINT}openai"

CONFIG_BLOCK=$(jq -n \
  --arg provider "$PROVIDER" \
  --arg disable "$DISABLE" \
  --arg baseURL "$BASE_URL" \
  --argjson whitelist "$WHITELIST" \
  --argjson models "$CUSTOM_MODELS" \
'{
  "disabled_providers": [$disable],
  "provider": {
    ($provider): {
      "options": {
        "baseURL": $baseURL
      },
      "whitelist": $whitelist,
      "models": $models
    }
  }
}')

if [[ "$SMOKE" == true ]]; then
  # ── Smoke mode: validate az login, endpoint, deployments, one live call ──────
  # Exits 0 on full success, non-zero on any failure. Writes nothing to disk.
  echo "" >&2
  echo "SMOKE: az login" >&2
  az account show --query "id" -o tsv >/dev/null || { echo "SMOKE FAIL: not logged in to az" >&2; exit 10; }
  echo "SMOKE PASS: az authenticated" >&2

  echo "SMOKE: endpoint" >&2
  [[ -n "$ENDPOINT" ]] || { echo "SMOKE FAIL: no endpoint resolved" >&2; exit 11; }
  echo "SMOKE PASS: endpoint=$ENDPOINT" >&2

  echo "SMOKE: deployments ($DEPLOY_COUNT found)" >&2
  (( DEPLOY_COUNT > 0 )) || { echo "SMOKE FAIL: no deployments" >&2; exit 12; }
  echo "SMOKE PASS: $DEPLOY_COUNT deployment(s) found" >&2

  echo "SMOKE: live chat/completions call to '$TEST_DEPLOY'" >&2
  if [[ "$HTTP_CODE" == "200" ]]; then
    echo "SMOKE PASS: HTTP 200 from $VERIFY_URL" >&2
    exit 0
  else
    echo "SMOKE FAIL: HTTP $HTTP_CODE from $VERIFY_URL" >&2
    [[ -n "${ERR_MSG:-}" ]] && echo "  Azure error: $ERR_MSG" >&2
    exit 13
  fi
fi

if [[ "$APPLY" == false ]]; then
  echo "" >&2
  echo "// ---- paste into opencode.json ----" >&2
  echo "// No env var required: provider.options.baseURL is written in config" >&2
  echo "// Optional env var mode: --set-env (session) or --persist-env (shell profile)" >&2
  echo "// API key: /connect in OpenCode, paste output of:" >&2
  echo "//   az cognitiveservices account keys list -g $RG -n $RES --query key1 -o tsv" >&2
  echo "" >&2
  echo "$CONFIG_BLOCK"
else
  # ── Apply: merge into opencode.json, set env var ──────────────────────────
  echo "" >&2
  echo "Applying configuration..." >&2

  # 8a. Optional env var setup (off by default)
  if [[ "$SET_ENV" == true ]]; then
    export "${ENV_VAR}=${RES}"
    echo "  Set $ENV_VAR in current shell session" >&2

    if [[ "$PERSIST_ENV" == true ]]; then
      SHELL_NAME=$(basename "${SHELL:-/bin/bash}")
      case "$SHELL_NAME" in
        zsh)  RC_FILE="$HOME/.zshrc";;
        *)    RC_FILE="$HOME/.bashrc";;
      esac
      if ! grep -qF "$ENV_VAR" "$RC_FILE" 2>/dev/null; then
        printf 'export %s=%q\n' "$ENV_VAR" "$RES" >> "$RC_FILE"
        echo "  Added $ENV_VAR to $RC_FILE" >&2
      else
        sed "/^export ${ENV_VAR}=/d" "$RC_FILE" > "${RC_FILE}.tmp"
        mv "${RC_FILE}.tmp" "$RC_FILE"
        printf 'export %s=%q\n' "$ENV_VAR" "$RES" >> "$RC_FILE"
        echo "  Updated $ENV_VAR in $RC_FILE" >&2
      fi
    fi
  else
    echo "  Skipped env var setup (config uses provider.options.baseURL)" >&2
  fi

  # 8b. Merge into opencode.json
  if [[ -f "$CONFIG_PATH" ]]; then
    EXISTING=$(cat "$CONFIG_PATH")
  else
    mkdir -p "$(dirname "$CONFIG_PATH")"
    EXISTING='{}'
  fi

  MERGED=$(echo "$EXISTING" | jq \
    --arg provider "$PROVIDER" \
    --arg disable "$DISABLE" \
    --arg baseURL "$BASE_URL" \
    --argjson whitelist "$WHITELIST" \
    --argjson models "$CUSTOM_MODELS" \
  '
    .disabled_providers = ((.disabled_providers // []) + [$disable] | unique) |
    .provider[$provider] = {
      "options": {"baseURL": $baseURL},
      "whitelist": $whitelist,
      "models": $models
    }
  ')

  echo "$MERGED" > "$CONFIG_PATH"
  echo "  Written to $CONFIG_PATH" >&2

  # 8c. Write API key to auth.json (same format as /connect writes)
  # Path: ~/.local/share/opencode/auth.json [OPENCODE-NORMATIVE: troubleshooting.mdx]
  AUTH_PATH="${HOME}/.local/share/opencode/auth.json"
  mkdir -p "$(dirname "$AUTH_PATH")"
  if [[ -f "$AUTH_PATH" ]]; then
    AUTH_JSON=$(cat "$AUTH_PATH")
  else
    AUTH_JSON='{}'
  fi
  # Format: { "<provider>": { "type": "api", "key": "<key>" } } [OPENCODE-NORMATIVE: sdk.mdx auth.set]
  # Atomic write (tmp + mv) to prevent corruption on interrupt
  echo "$AUTH_JSON" | jq \
    --arg provider "$PROVIDER" \
    --arg key "$API_KEY" \
    '.[$provider] = {"type": "api", "key": $key}' > "${AUTH_PATH}.tmp"
  mv "${AUTH_PATH}.tmp" "$AUTH_PATH"
  chmod 600 "$AUTH_PATH"
  echo "  API key written to $AUTH_PATH" >&2

  # Clear key from memory
  unset API_KEY

  echo "" >&2
  echo "DONE. Fully configured -- restart OpenCode to pick up changes." >&2
  if [[ "$PERSIST_ENV" == true ]]; then
    echo "  Run: source $RC_FILE" >&2
  fi
fi
