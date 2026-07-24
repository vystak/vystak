# Changelog

All notable changes to Vystak are documented here.

## Unreleased

### Added

- **Folder skills** — a skill can now be a folder of packaged instructions
  (`skills/<name>/SKILL.md` with `name`/`description`/`tools` frontmatter,
  plus resource files) declared with string shorthand (`skills: [research]`)
  or an explicit project-relative `path:`. Resolved at load time
  (`vystak.schema.skill_resolver`); the folder's content digest feeds the
  agent hash, so editing any bundled skill file surfaces as a redeploy in
  `vystak plan`. At runtime agents get progressive disclosure: the system
  prompt lists each skill's name + description, and auto-provided
  `load_skill` / `read_skill_file` tools fetch instructions and resources
  on demand. New examples: `docker-skills` (chat) and `docker-skills-slack`
  (Slack channel + tools + folder skill).

- New package `vystak-channel-runtime` — shared template-method runtime for
  all channel containers (`ChannelRuntime`, `AgentClient`, `ChannelStore`).
- New package `vystak-channel-discord` — Discord channel built on the
  shared runtime. Slack-parity routing, threads, slash commands, single-agent
  auto-bind; streaming and status reactions are deferred.

### Changed

- Inline skill `prompt` fields are now actually appended to the agent's
  system prompt (previously documented but unimplemented). `Skill` gained a
  `description` field, surfaced in the prompt listing and the A2A agent card.
- Default `pytest` runs now exclude **all** release-tier markers
  (`release_smoke`, `release_integration`, etc.) via root `addopts`,
  matching the documented "gated by default" contract; previously only
  `-m 'not docker'` was excluded, so some release cells ran in
  `just test-python`.
- `vystak-channel-slack` and `vystak-channel-chat` retrofitted onto
  `vystak-channel-runtime`. User-visible behavior preserved.
- Channel containers no longer have generated `server.py` files. Each channel
  package is now a real importable library invoked as
  `python -m vystak_channel_<type>`. The plugin's `generate_code()` emits
  only `Dockerfile`, `requirements.txt`, `channel_config.json`, and
  `routes.json`.

### Breaking

- **Empty placeholder skills are now a load-time error.** A skill with no
  `tools`, no `prompt`, and no matching `skills/<name>/SKILL.md` folder
  fails `vystak plan`/`apply` with an actionable message (previously it
  loaded silently and did nothing). Fix: delete the placeholder, declare
  tools, or create the skill folder. All in-repo examples are migrated.
- **One-time redeploy on upgrade**: the new `Skill` fields enter the
  content hash, so every agent's hash changes once.
- **Slack thread bindings + route prefs reset on upgrade.** The runtime store
  uses a new generic schema keyed by `(channel_type, scope_id, thread_id)`.
  Existing `routes.db` (SQLite) and `routes` table (Postgres) are ignored.
  Re-route via `/vystak route ...` after upgrade — auto-bind on mention
  repopulates organically.
- **Container entrypoint changed** from `python server.py` to
  `python -m vystak_channel_<type>`. `vystak apply` regenerates the
  Dockerfile so most users will not notice; downstream consumers with custom
  Dockerfiles will need to update.

---

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
- ~~**Vault path + channels with secrets (security gap).**~~ **Fixed.**
  `DockerProvider._add_vault_nodes` now enumerates channel principals
  alongside agent + workspace, creating one AppRole + Vault Agent
  sidecar per channel with declared secrets. `apply_channel` wires
  the channel container to its sidecar's `/shared` volume;
  `DockerChannelNode` skips the `os.environ` passthrough when a vault
  context is set, so channel secrets reach the container via the
  Vault-rendered `/shared/secrets.env` exclusively. `vystak plan`
  output gains `<channel>-channel` rows in the AppRoles/Policies
  sections for Hashi Vault configs. Release cells D5 and D8 pass
  end-to-end.

### Specs / plans

- Original design: `docs/superpowers/specs/2026-04-19-secret-manager-design.md`
- HashiCorp backend: `docs/superpowers/specs/2026-04-20-hashicorp-vault-backend-design.md`
- Simplification design: `docs/superpowers/specs/2026-04-22-secret-manager-simplification-design.md`
- Simplification implementation: `docs/superpowers/plans/2026-04-23-secret-manager-simplification.md`
