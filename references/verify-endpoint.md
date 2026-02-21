# Verify Azure Endpoint

Quick smoke tests to confirm the Azure AI endpoint and API key work before configuring OpenCode.

## PowerShell

```powershell
$key = "<YOUR_API_KEY>"
$resource = "<RESOURCE_NAME>"
$deployment = "<DEPLOYMENT_NAME>"  # e.g., gpt-4o

$body = '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":10}'

Invoke-WebRequest `
  -Uri "https://$resource.cognitiveservices.azure.com/openai/deployments/$deployment/chat/completions?api-version=2024-12-01-preview" `
  -Method Post `
  -Headers @{"api-key"=$key} `
  -ContentType "application/json" `
  -Body $body
```

For `*.openai.azure.com` resources, replace `.cognitiveservices.azure.com` with `.openai.azure.com`.

## Bash / curl

```bash
KEY="<YOUR_API_KEY>"
RESOURCE="<RESOURCE_NAME>"
DEPLOYMENT="<DEPLOYMENT_NAME>"

curl -s "https://${RESOURCE}.cognitiveservices.azure.com/openai/deployments/${DEPLOYMENT}/chat/completions?api-version=2024-12-01-preview" \
  -H "api-key: ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":10}'
```

## Expected result

A JSON response containing `"choices"` with a `"message"` object. Any HTTP 200 with content confirms the endpoint works.

## Common failures

| Status | Meaning |
|---|---|
| 401 | Bad API key. Re-fetch with `az cognitiveservices account keys list` |
| 404 | Deployment name doesn't exist. Check `az cognitiveservices account deployment list` |
| 403 | Network/firewall restriction on the resource |
