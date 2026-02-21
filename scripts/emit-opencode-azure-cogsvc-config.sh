#!/usr/bin/env bash
# emit-opencode-azure-cogsvc-config.sh
# Discovers Azure AI Services deployments and emits/applies an opencode.json provider block.
# All parameters optional. With zero args, scans all subscriptions and auto-picks best resource.
#
# Requirements: az (authenticated), jq
# Usage:
#   ./emit-opencode-azure-cogsvc-config.sh                                      # full auto, dry run
#   ./emit-opencode-azure-cogsvc-config.sh --apply                              # full auto, apply
#   ./emit-opencode-azure-cogsvc-config.sh --subscription <id> --resource <name>
#   ./emit-opencode-azure-cogsvc-config.sh --subscription <id> --apply
set -euo pipefail

SUB="" RES="" RG="" APPLY=false
CONFIG_PATH="${HOME}/.config/opencode/opencode.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUB="$2"; shift 2;;
    --resource)     RES="$2"; shift 2;;
    --rg)           RG="$2";  shift 2;;
    --apply)        APPLY=true; shift;;
    --config)       CONFIG_PATH="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

# ── Step 1: Find subscription ──────────────────────────────────────────────────
if [[ -z "$SUB" ]]; then
  echo "Scanning all subscriptions for AI resources..." >&2
  BEST_COUNT=0
  while IFS=$'\t' read -r sub_id sub_name; do
    while IFS=$'\t' read -r name rg; do
      count=$(az cognitiveservices account deployment list \
        --subscription "$sub_id" -g "$rg" -n "$name" --query "length([])" -o tsv 2>/dev/null || echo 0)
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
    count=$(az cognitiveservices account deployment list -g "$rg" -n "$name" --query "length([])" -o tsv 2>/dev/null || echo 0)
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
echo "$DEPLOY_JSON" | jq -r '.[] | "  \(.name)" + (if (.name | ascii_downcase) != (.properties.model.name | ascii_downcase) then " (model: \(.properties.model.name))" else "" end)' >&2

# ── Step 6: Build whitelist + models block ────────────────────────────────────
WHITELIST=$(echo "$DEPLOY_JSON" | jq -r '
  [.[] | .name, .properties.model.name]
  | map(ascii_downcase)
  | unique
  | sort
')

CUSTOM_MODELS=$(echo "$DEPLOY_JSON" | jq '
  [.[] | select((.name | ascii_downcase) != (.properties.model.name | ascii_downcase))
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
VERIFY_URL="${ENDPOINT}openai/deployments/${TEST_DEPLOY}/chat/completions?api-version=2024-12-01-preview"
VERIFY_RESP=$(curl -s -w "\n%{http_code}" "$VERIFY_URL" \
  -H "api-key: ${API_KEY}" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say ok"}],"max_tokens":5}')
HTTP_CODE=$(echo "$VERIFY_RESP" | tail -1)
if [[ "$HTTP_CODE" == "200" ]]; then
  echo "Endpoint verified (HTTP 200)" >&2
else
  echo "WARNING: Endpoint returned HTTP $HTTP_CODE. Config will still be generated." >&2
fi

# ── Step 8: Build output ─────────────────────────────────────────────────────
CONFIG_BLOCK=$(jq -n \
  --arg provider "$PROVIDER" \
  --arg disable "$DISABLE" \
  --argjson whitelist "$WHITELIST" \
  --argjson models "$CUSTOM_MODELS" \
'{
  "disabled_providers": [$disable],
  "provider": {
    ($provider): {
      "whitelist": $whitelist,
      "models": $models
    }
  }
}')

if [[ "$APPLY" == false ]]; then
  echo "" >&2
  echo "// ---- paste into opencode.json ----" >&2
  echo "// Env var: $ENV_VAR=$RES" >&2
  echo "// API key: /connect in OpenCode, paste output of:" >&2
  echo "//   az cognitiveservices account keys list -g $RG -n $RES --query key1 -o tsv" >&2
  echo "" >&2
  echo "$CONFIG_BLOCK"
else
  # ── Apply: merge into opencode.json, set env var ──────────────────────────
  echo "" >&2
  echo "Applying configuration..." >&2

  # 8a. Set env var persistently
  SHELL_NAME=$(basename "${SHELL:-/bin/bash}")
  case "$SHELL_NAME" in
    zsh)  RC_FILE="$HOME/.zshrc";;
    *)    RC_FILE="$HOME/.bashrc";;
  esac
  EXPORT_LINE="export $ENV_VAR=\"$RES\""
  if ! grep -qF "$ENV_VAR" "$RC_FILE" 2>/dev/null; then
    echo "$EXPORT_LINE" >> "$RC_FILE"
    echo "  Added $ENV_VAR to $RC_FILE" >&2
  else
    sed -i.bak "s|^export ${ENV_VAR}=.*|${EXPORT_LINE}|" "$RC_FILE"
    echo "  Updated $ENV_VAR in $RC_FILE" >&2
  fi
  eval "$EXPORT_LINE"

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
    --argjson whitelist "$WHITELIST" \
    --argjson models "$CUSTOM_MODELS" \
  '
    .disabled_providers = ((.disabled_providers // []) + [$disable] | unique) |
    .provider[$provider] = {
      "whitelist": $whitelist,
      "models": $models
    }
  ')

  echo "$MERGED" > "$CONFIG_PATH"
  echo "  Written to $CONFIG_PATH" >&2

  # 8c. Print remaining manual step
  echo "" >&2
  echo "DONE. One manual step remains:" >&2
  echo "  1. Open OpenCode" >&2
  echo "  2. Run /connect -> select '$PROVIDER'" >&2
  echo "  3. Paste this API key: $API_KEY" >&2
  echo "" >&2
  echo "  Then: source $RC_FILE" >&2
fi
