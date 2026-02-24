#!/usr/bin/env bash
set -euo pipefail

# Live e2e: Azure (az) + OpenCode (opencode)
#
# Detects the current failure mode:
# - Azure reports a deployment exists
# - OpenCode can list the model but cannot run it (DeploymentNotFound)

RESOURCE="${AZURE_COGNITIVE_SERVICES_RESOURCE_NAME:-}"
if [ -z "$RESOURCE" ]; then
  echo "error: AZURE_COGNITIVE_SERVICES_RESOURCE_NAME is not set" >&2
  exit 2
fi

KEY="${AZURE_AI_KEY:-${AZURE_OPENAI_API_KEY:-}}"
if [ -z "$KEY" ]; then
  echo "error: set AZURE_AI_KEY or AZURE_OPENAI_API_KEY" >&2
  exit 2
fi

AZ_TIMEOUT_SECONDS="${AZURE_AZ_TIMEOUT_SECONDS:-60}"
LLAMA_ID="llama-4-maverick-17b-128e-instruct-fp8"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export XDG_CONFIG_HOME="$tmp/xdg-config"
export XDG_DATA_HOME="$tmp/xdg-data"
export AZURE_OPENAI_API_KEY="$KEY"

config_path="$XDG_CONFIG_HOME/opencode/opencode.json"
auth_path="$XDG_DATA_HOME/opencode/auth.json"

mkdir -p "$(dirname "$config_path")" "$(dirname "$auth_path")"
printf '%s\n' '{}' >"$config_path"
printf '%s\n' '{}' >"$auth_path"

uv run azure-opencode-setup setup \
  --provider-id azure-cognitive-services \
  --resource-name "$RESOURCE" \
  --az-timeout-seconds "$AZ_TIMEOUT_SECONDS" \
  --config-path "$config_path" \
  --auth-path "$auth_path"

echo "--- opencode models (refresh) ---"
opencode models azure-cognitive-services --refresh

if ! opencode models azure-cognitive-services | grep -q "azure-cognitive-services/$LLAMA_ID"; then
  echo "error: OpenCode models list missing $LLAMA_ID" >&2
  exit 1
fi

echo "--- opencode run sanity (gpt-4o) ---"
opencode run --format json -m "azure-cognitive-services/gpt-4o" ping >/dev/null

echo "--- opencode run target ($LLAMA_ID) ---"
opencode run --format json -m "azure-cognitive-services/$LLAMA_ID" ping >/dev/null

echo "--- opencode run case-mapped (deepseek-v3.1) ---"
opencode run --format json -m "azure-cognitive-services/deepseek-v3.1" ping >/dev/null

echo "--- opencode run model->deployment mapped (kimi-k2-thinking) ---"
opencode run --format json -m "azure-cognitive-services/kimi-k2-thinking" ping >/dev/null

echo "OK: OpenCode can run key deployments"
