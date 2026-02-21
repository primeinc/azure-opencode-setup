#!/usr/bin/env bash
# emit-opencode-azure-cogsvc-config.sh
# Discovers Azure AI Services deployments and emits a ready-to-paste opencode.json provider block.
#
# Requirements: az (authenticated), jq
# Usage:
#   ./emit-opencode-azure-cogsvc-config.sh --subscription <id> --resource <name> [--rg <group>]
#   ./emit-opencode-azure-cogsvc-config.sh --subscription <id>  # auto-picks resource with most deployments
set -euo pipefail

SUB="" RES="" RG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUB="$2"; shift 2;;
    --resource)     RES="$2"; shift 2;;
    --rg)           RG="$2";  shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

[[ -z "$SUB" ]] && { echo "ERROR: --subscription required" >&2; exit 2; }

az account set --subscription "$SUB" >/dev/null

# If no resource specified, find all AI Services/OpenAI resources and pick the one with most deployments
if [[ -z "$RES" ]]; then
  echo "WARNING: No --resource specified. Scanning subscription for AI resources..." >&2
  ACCOUNTS=$(az cognitiveservices account list \
    --query "[?kind=='AIServices' || kind=='OpenAI'].[name, resourceGroup]" -o tsv)
  if [[ -z "$ACCOUNTS" ]]; then
    echo "ERROR: No AIServices or OpenAI resources found in subscription $SUB" >&2; exit 3
  fi
  BEST_COUNT=0
  while IFS=$'\t' read -r name rg; do
    count=$(az cognitiveservices account deployment list -g "$rg" -n "$name" --query "length([])" -o tsv 2>/dev/null || echo 0)
    echo "  $name ($rg): $count deployments" >&2
    if (( count > BEST_COUNT )); then
      BEST_COUNT=$count; RES="$name"; RG="$rg"
    fi
  done <<< "$ACCOUNTS"
  echo "Selected: $RES ($BEST_COUNT deployments)" >&2

  # Warn if multiple resources exist
  RESOURCE_COUNT=$(echo "$ACCOUNTS" | wc -l | tr -d ' ')
  if (( RESOURCE_COUNT > 1 )); then
    echo "WARNING: $RESOURCE_COUNT resources found. Use --resource <name> to target a specific one." >&2
    echo "NOTE: One provider config = one resource. Only '$RES' will be configured." >&2
  fi
fi

# Resolve resource group if not provided
if [[ -z "$RG" ]]; then
  RG=$(az resource list --name "$RES" --resource-type "Microsoft.CognitiveServices/accounts" \
    --query "[0].resourceGroup" -o tsv)
fi
[[ -z "$RG" ]] && { echo "ERROR: Could not find resource group for '$RES'" >&2; exit 3; }

# Get endpoint (source of truth for provider type)
ENDPOINT=$(az cognitiveservices account show -g "$RG" -n "$RES" --query "properties.endpoint" -o tsv)
[[ -z "$ENDPOINT" ]] && { echo "ERROR: No endpoint for $RES" >&2; exit 4; }

# Determine provider from endpoint pattern [MICROSOFT-NORMATIVE]
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

# List deployments: get both deployment name and model name [MICROSOFT-NORMATIVE: deployment name is truth]
DEPLOY_JSON=$(az cognitiveservices account deployment list -g "$RG" -n "$RES" -o json)

# Build whitelist: deployment names (lowercased) + model names (lowercased) when they differ
# Rule: deployment name is primary. Model name added for catalog compatibility.
WHITELIST=$(echo "$DEPLOY_JSON" | jq -r '
  [.[] | .name, .properties.model.name]
  | map(ascii_downcase)
  | unique
  | sort
')

# Build models block: only for deployments not in the built-in catalog (deployment != model name)
CUSTOM_MODELS=$(echo "$DEPLOY_JSON" | jq '
  [.[] | select(.name != .properties.model.name and (.properties.model.name | test("^(gpt|o[0-9]|text-)") | not))]
  | if length > 0 then
      reduce .[] as $d ({}; .[$d.name | ascii_downcase] = {"name": ("\($d.properties.model.name) (Azure)")})
    else {} end
')

# Emit ready-to-paste JSON
echo "// ---- paste into opencode.json ----" >&2
echo "// Provider: $PROVIDER | Resource: $RES | Endpoint: $ENDPOINT" >&2
echo "// Env var to set: $ENV_VAR=$RES" >&2
echo "// API key: run /connect in OpenCode -> paste key from:" >&2
echo "//   az cognitiveservices account keys list -g $RG -n $RES --query key1 -o tsv" >&2
echo "" >&2

jq -n \
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
}'
