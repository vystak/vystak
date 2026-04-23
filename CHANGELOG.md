# Changelog

All notable changes to Vystak are documented here.

## [Unreleased]

### Secrets (default path + opt-in Vault)

`Secret` declarations on an `Agent`, its `Workspace`, or a `Channel`
materialize **only** into that principal's container environment. Delivery
uses platform-native mechanisms by default:

- **Docker:** per-container `--env-file=.vystak/env/<principal>.env` at
  `vystak apply` time.
- **Azure ACA:** inline `configuration.secrets[]` + per-container
  `env[].secretRef`.

The per-container isolation guarantee — "the LLM in the agent container
cannot reach workspace-scoped secrets" — is preserved by the container
boundary, not by Vault.

**Vault is an opt-in feature** for users who want rotation, an audit log
of reads, or shared secret storage across multiple deploys. Two backends
are available when declared:

- `Vault(type="vault", provider=docker)` — HashiCorp Vault server +
  per-principal AppRoles + Vault Agent sidecars rendering `/shared/secrets.env`.
- `Vault(type="key-vault", provider=azure)` — Azure Key Vault + per-principal
  UAMI + `identitySettings[].lifecycle: None`.

### CLI

- `vystak secrets list` — declared secrets + presence (`[env-only]` on
  default path, `present/absent in vault` when declared).
- `vystak secrets push` — on the default path, previews resolution from
  `.env`; with a Vault declared, pushes to the declared backend with
  push-if-missing semantics (`--force` overwrites; `--allow-missing`
  skips missing-from-env entries).
- `vystak secrets set NAME=VALUE` — writes directly to the declared
  backend; on the default path, rejects with guidance to edit `.env`.
- `vystak secrets diff` — compares `.env` vs. declared backend, prints
  only names + categories (`same` / `differs` / `env-only` /
  `vault-only` / `missing`). Never prints values.
- `vystak secrets rotate-approle <principal>` — Hashi-only. Rotates
  AppRole credentials, restarts the sidecar.
- `vystak secrets rotate-ssh <agent>` — regenerates the workspace SSH
  keypair. On the default path, writes to `.vystak/ssh/<agent>/`. With
  Vault declared, pushes to `_vystak/workspace-ssh/<agent>/*`.
- `vystak plan` — on the default path, emits an `EnvFiles:` section with
  per-principal resolution counts; detects orphan Vault resources from a
  previous deploy and prints the migration command. `Vault:` /
  `Identities:` / `Grants:` sections are Vault-only.
- `vystak destroy` — on the default path, cleans `.vystak/env/` and
  `.vystak/ssh/` after provider teardown. Vault-path state
  (`init.json`, approle/secrets volumes) stays under `--delete-vault`
  control.

### Runtime SDK

`vystak.secrets.get(name) → str` — thin wrapper around
`os.environ[name]` with a clearer error when the secret isn't wired
into the caller's principal. Works identically on both paths.

### Schema

Three cross-object validators were removed from `multi_loader.py`:
- "workspace secrets on Docker requires Hashi Vault"
- "workspace secrets on non-Azure, non-Docker rejected"
- "workspace requires a Vault for SSH key storage"

`Vault.type` ↔ `Provider.type` pairing is still enforced when a Vault is
declared: `key-vault` requires `provider.type="azure"`, `vault` requires
`provider.type="docker"`. Opting into Hashi-on-ACA or KV-on-Docker is a
follow-up spec.

### Migration

| Situation | After ship | Action needed |
|---|---|---|
| Has `vault:` declared, wants Vault features | Deploy identical | None |
| Has `vault:` declared because the validator forced it | Can remove the block for the fast default path | Optional — run `vystak destroy --delete-vault && vystak apply` first to reclaim Vault resources |
| Fresh user, no existing deploy | Writes schema without `vault:` and gets the default path | None |

Removing the `vault:` block on an existing deploy triggers a plan-time
warning listing orphan resources (`vystak-vault` container,
`-vault-agent` sidecars, `init.json`, `-approle`/`-secrets` volumes)
with the cleanup command. Orphan resources are not auto-destroyed —
unseal keys exist nowhere else, so accidental removal would be
irreversible.

### Security envelope (default path vs. Vault path)

| Concern | Default | Vault |
|---|---|---|
| LLM-in-agent reads workspace secret from env / /proc / memory | Blocked — not present in agent's process | Blocked — same |
| Cross-container token fetch (Azure IMDS) | No UAMI attached → no attack surface | `lifecycle:None` blocks |
| ARM-template readability on Azure | Plaintext visible to Reader role | KV refs only |
| Host compromise blast radius | `.env` + `.vystak/env/*` — current values only | `.vystak/vault/init.json` — root token → current + historical + write |
| Audit log of fetches | None | Yes |
| Rotation workflow | Edit `.env`, re-apply | `vystak secrets push --force` |

### Known follow-up work

- Wiring `build_revision_for_vault` / `build_revision_default_path` into
  `ContainerAppNode.provision` so Azure multi-container workspace
  deploys actually produce multi-container ACA revisions. (Both helpers
  are unit-tested but neither is plumbed into deploy today; the gap
  predates this release.)
- Generating `known_hosts` for default-path agent → workspace SSH RPC
  so the built-in `fs.*` / `exec.*` / `git.*` workspace tools work
  end-to-end without Vault.
- Hashi Vault on Azure ACA; Azure Key Vault as an external store on
  Docker.
- **Vault path + channels with secrets (security gap).**
  `DockerProvider._add_vault_nodes` enumerates agent + workspace
  principals but not channels. Channel-declared secrets get pushed to
  Vault KV at apply time, but no per-channel AppRole or Vault Agent
  sidecar is created — `DockerChannelNode` silently falls back to
  `os.environ` passthrough, defeating Vault's isolation guarantee for
  channel secrets. Surfaced by release-tier cells D5 and D8 (marked
  `pytest.mark.xfail(strict=True)` pending fix). Fix is symmetric
  with the existing principal enumeration: loop over channels with
  declared secrets and create one AppRole + sidecar per channel.

### Specs / plans

- Original design: `docs/superpowers/specs/2026-04-19-secret-manager-design.md`
- HashiCorp backend: `docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`
- Simplification design: `docs/superpowers/specs/2026-04-22-secret-manager-simplification-design.md`
- Simplification implementation: `docs/superpowers/plans/2026-04-23-secret-manager-simplification.md`
