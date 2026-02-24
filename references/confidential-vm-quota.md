# Confidential VM Quota (DCasv5/ECasv5)

This is a pre-flight checklist for Azure Confidential VMs that provide encryption-in-use (memory protection) via VM families like DCasv5/ECasv5.

## 1) Pick subscription + region

```bash
az account show --query "{sub:name,id:id,user:user.name}" -o json
az account list --query "[].{name:name,id:id,state:state}" -o table
az account set --subscription "<SUB_NAME_OR_ID>"
```

Pick a target region (example: `eastus`, `westeurope`).

## 2) Confirm the region exposes DCasv5/ECasv5 SKUs

```bash
REGION=eastus

az vm list-skus -l $REGION --all \
  --query "[?contains(name,'DCasv5') || contains(name,'ECasv5')].{sku:name,restrictions:length(restrictions)}" \
  -o table
```

If nothing returns, treat the region as unsupported for these families in this subscription.

## 3) Check current quota (cores) for the VM families

```bash
REGION=eastus

az vm list-usage -l $REGION \
  --query "[?contains(name.value,'DCASv5') || contains(name.value,'ECASv5')].{name:name.value,used:currentValue,limit:limit}" \
  -o table
```

If the family limit is `0`, you cannot deploy these VMs until quota is increased.

## 4) Request quota increase

Quota increases for specialized VM families are often handled via a support request.

Portal path:
- Azure Portal -> Help + support -> Create a support request
- Issue type: `Service and subscription limits (quotas)`
- Service: `Compute`
- Quota type: `Cores`
- Region: your target region
- Request increases for:
  - `standardDCASv5Family`
  - `standardECASv5Family`

## Notes

- The Azure Support REST API (and `az support ...`) may be blocked for some support plans. If CLI ticket creation fails with `InvalidSupportPlan`, use the Portal flow above or upgrade the Azure support plan.
- If you run Azure CLI from Git Bash / MSYS on Windows and pass an ARM ID that starts with `/providers/...`, disable path conversion:

```bash
MSYS_NO_PATHCONV=1 az support services list -o table
```
