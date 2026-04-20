# Changelog

All notable changes to Vystak are documented here.

## [Unreleased]

### Added
- `Vault` top-level schema resource for Azure Key Vault-backed secrets.
- `Workspace.secrets` and `Workspace.identity` for tool-secret isolation from the LLM.
- Azure provider: per-container `secretRef` + `lifecycle: None` UAMIs with narrow Key Vault Secrets User RBAC.
- `vystak.secrets.get()` runtime helper.
- `vystak secrets` CLI: `list`, `push`, `set`, `diff`.
- `.env`-based secret bootstrap at `vystak apply` with push-if-missing semantics; `--force` overwrites.

### Limitations
- v1 supports Azure Key Vault only. HashiCorp Vault is a follow-up spec.
- Workspace stays 1:1 with agent; multi-agent workspace sharing and exec sandboxes are follow-ups.
- Per-user/per-session scope is a follow-up spec.
