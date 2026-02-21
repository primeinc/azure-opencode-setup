# Verify Azure Endpoint

Smoke test the endpoint before configuring OpenCode. Use whatever `az cognitiveservices account show --query properties.endpoint` returns — that is the source of truth [MICROSOFT-NORMATIVE].

## Determine your endpoint type

```bash
az cognitiveservices account show -g <RG> -n <RESOURCE> --query "properties.endpoint" -o tsv
```

## Cognitive Services endpoint (`*.cognitiveservices.azure.com`)

### PowerShell

```powershell
$key = az cognitiveservices account keys list -g <RG> -n <RESOURCE> --query "key1" -o tsv
$resource = "<RESOURCE_NAME>"
$deployment = "<DEPLOYMENT_NAME>"  # e.g., gpt-4o

Invoke-RestMethod `
  -Uri "https://$resource.cognitiveservices.azure.com/openai/deployments/$deployment/chat/completions?api-version=2024-12-01-preview" `
  -Method Post `
  -Headers @{"api-key"=$key} `
  -ContentType "application/json" `
  -Body '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":10}'
```

### Bash

```bash
KEY=$(az cognitiveservices account keys list -g <RG> -n <RESOURCE> --query "key1" -o tsv)
RESOURCE="<RESOURCE_NAME>"
DEPLOYMENT="<DEPLOYMENT_NAME>"

curl -s "https://${RESOURCE}.cognitiveservices.azure.com/openai/deployments/${DEPLOYMENT}/chat/completions?api-version=2024-12-01-preview" \
  -H "api-key: ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":10}'
```

## OpenAI endpoint (`*.openai.azure.com`)

### PowerShell

```powershell
$key = az cognitiveservices account keys list -g <RG> -n <RESOURCE> --query "key1" -o tsv
$resource = "<RESOURCE_NAME>"
$deployment = "<DEPLOYMENT_NAME>"

Invoke-RestMethod `
  -Uri "https://$resource.openai.azure.com/openai/deployments/$deployment/chat/completions?api-version=2024-12-01-preview" `
  -Method Post `
  -Headers @{"api-key"=$key} `
  -ContentType "application/json" `
  -Body '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":10}'
```

### Bash

```bash
KEY=$(az cognitiveservices account keys list -g <RG> -n <RESOURCE> --query "key1" -o tsv)
RESOURCE="<RESOURCE_NAME>"
DEPLOYMENT="<DEPLOYMENT_NAME>"

curl -s "https://${RESOURCE}.openai.azure.com/openai/deployments/${DEPLOYMENT}/chat/completions?api-version=2024-12-01-preview" \
  -H "api-key: ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Say hello"}],"max_tokens":10}'
```

## Expected result

HTTP 200 with JSON containing `"choices"` array. Any response with `choices[0].message.content` confirms the endpoint + deployment works.

## Failure codes

| Status | Meaning | Fix |
|---|---|---|
| 401 | Bad API key | Re-fetch: `az cognitiveservices account keys list` |
| 404 | Deployment doesn't exist | Check: `az cognitiveservices account deployment list` |
| 403 | Network/firewall rule blocking | Check resource networking in Azure portal |
| 429 | Quota exhausted | See `quota-validation.md` |
