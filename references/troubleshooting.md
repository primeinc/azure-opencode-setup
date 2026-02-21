# Troubleshooting Azure + OpenCode

## "The API deployment for this resource does not exist" (404)

The model is in the OpenCode catalog but not deployed on your Azure resource.

Fix:
- Deploy it via [Azure AI Foundry](https://ai.azure.com/) or `az cognitiveservices account deployment create`
- Or remove it from your `whitelist` in opencode.json

## 401 PermissionDenied

API key is invalid or rotated.

Fix:
- Verify key: `az cognitiveservices account keys list -g <RG> -n <RESOURCE>`
- Re-run `/connect` in opencode with the fresh key

## Wrong endpoint pattern

If using `*.openai.azure.com` resource with `azure-cognitive-services` provider (or vice versa):

| Resource endpoint | Correct provider | Correct env var |
|---|---|---|
| `*.cognitiveservices.azure.com` | `azure-cognitive-services` | `AZURE_COGNITIVE_SERVICES_RESOURCE_NAME` |
| `*.openai.azure.com` | `azure` | `AZURE_RESOURCE_NAME` |

Fix:
- Switch to the correct provider in `/connect`
- Set the correct env var
- Disable the wrong provider: `"disabled_providers": ["azure"]` or `["azure-cognitive-services"]`

## Full model catalog still showing (~90 models)

The `whitelist` feature is not taking effect.

Fix:
- Ensure `whitelist` is inside the correct provider block:
  ```json
  {
    "provider": {
      "azure-cognitive-services": {
        "whitelist": ["gpt-4o", "deepseek-v3.2"]
      }
    }
  }
  ```
- Restart opencode after config changes
- Check for JSON syntax errors in opencode.json

## Duplicate azure/* and azure-cognitive-services/* entries

Both providers are active and pointing to the same resource.

Fix:
- Add `"disabled_providers": ["azure"]` (if using cognitive services endpoint)
- Or `"disabled_providers": ["azure-cognitive-services"]` (if using openai endpoint)

## "reasoning_effort" or unsupported parameter errors

Some Azure model deployments don't support all parameters that OpenCode sends.

Reference: [GH #12113](https://github.com/anomalyco/opencode/issues/12113), [GH #12121](https://github.com/anomalyco/opencode/issues/12121)

## Case sensitivity

Azure deployment names are **case-insensitive** in API calls. `DeepSeek-V3.2` and `deepseek-v3.2` resolve to the same deployment. Use lowercase in `whitelist` to match the built-in catalog.
