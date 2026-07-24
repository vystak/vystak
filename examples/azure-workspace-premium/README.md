# azure-workspace-premium

Single agent whose workspace volume (`fast-scratch`) is backed by **Azure
Files NFS** instead of the default SMB share, via `performance: premium` on
a named `Volume`. NFS is markedly faster than SMB for git/npm/pip-heavy
workloads (small-file metadata operations), at the cost of two extra
prerequisites SMB doesn't need.

## What this demonstrates

- A top-level `volumes:` block declaring `fast-scratch` as
  `mode: persistent, performance: premium`
- The agent's `workspace:` referencing it via `volume: fast-scratch`
- Azure maps a premium volume to an Azure Files **NFS** share (vs. the
  standard SMB share `performance: standard` — the default — produces)

## Prerequisites

Azure Files NFS on Container Apps requires two things that plain
`performance: standard` (SMB) does not. `vystak apply` fails fast with an
actionable error if either is missing:

1. **A `FileStorage`-kind, `Premium_LRS` storage account.** Standard
   (`StorageV2`) accounts don't support NFS. Create one:

   ```bash
   az storage account create -n <name> -g vystak-ws-premium-rg \
       --kind FileStorage --sku Premium_LRS
   ```

2. **A VNet-injected Container Apps environment.** NFS mounts require the
   ACA environment to have `vnetConfiguration.infrastructureSubnetId` set —
   this cannot be added to an existing environment after the fact, and
   `vystak apply` does not provision VNet injection itself. Create the
   environment yourself with `--infrastructure-subnet-resource-id`, then
   point this example at it via `providers.azure.config.environment` (or
   use `performance: standard` (SMB), which works against any environment).

## Configure

`vystak.yaml`'s `${AZURE_STORAGE_ACCOUNT}` / `${AZURE_ACA_ENVIRONMENT}`
are documentation placeholders, not shell interpolation — the loader does
not expand them. **Edit `vystak.yaml` directly** and replace them with real
values:

- `providers.azure.config.storage_account` — name of the `FileStorage`
  account from step 1
- `providers.azure.config.environment` — name of the VNet-injected ACA
  environment from step 2
- `providers.azure.config.resource_group` / `location` — must match where
  the storage account and environment already exist

## Run

```bash
az login   # or export AZURE_SUBSCRIPTION_ID
cp .env.example .env     # then edit and fill in ANTHROPIC_API_KEY, storage account, and ACA environment
# vystak.yaml must already have storage_account / environment filled in — see Configure above

vystak plan     # preview — fails here with the actionable errors above if
                # the storage account isn't FileStorage/Premium_LRS or the
                # environment isn't VNet-injected
vystak apply    # create vault + UAMI + NFS share + ACA app
vystak destroy  # tear down the resource group (the Files share itself is
                # never deleted automatically — see "Cleanup" below)
```

## Cleanup

Named shared volumes on Azure are never auto-deleted by `vystak destroy` —
the share lives in your storage account, outside the resource group vystak
manages. Remove it manually once you're done:

```bash
az storage share delete --account-name <your-filestorage-account-name> \
    --name vystak-volume-fast-scratch
```
