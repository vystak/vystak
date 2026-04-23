"""Generators for Vault HCL configs and the entrypoint shim.

All outputs are deterministic given their inputs — no timestamps, no
hashes. Tests assert byte-level expectations on generated strings.
"""


def generate_server_hcl(*, port: int = 8200) -> str:
    """Vault server config: file storage, single TCP listener, TLS disabled
    (internal Docker network only)."""
    return f"""\
storage "file" {{
  path = "/vault/file"
}}

listener "tcp" {{
  address     = "0.0.0.0:{port}"
  tls_disable = true
}}

ui = false
disable_mlock = true
"""


def generate_agent_hcl(*, vault_address: str, secret_names: list[str]) -> str:
    """Vault Agent config: AppRole auto-auth + single template that renders
    secrets.env with one KEY=value line per declared secret."""
    template_body = []
    for name in secret_names:
        template_body.append(
            f'    {{{{- with secret "secret/data/{name}" }}}}\n'
            f"    {name}={{{{ .Data.data.value }}}}\n"
            "    {{- end }}"
        )
    template_contents = "\n".join(template_body) if template_body else ""

    return f"""\
exit_after_auth = false
pid_file        = "/tmp/vault-agent.pid"

vault {{
  address = "{vault_address}"
}}

auto_auth {{
  method "approle" {{
    config = {{
      role_id_file_path   = "/vault/approle/role_id"
      secret_id_file_path = "/vault/approle/secret_id"
      remove_secret_id_file_after_reading = false
    }}
  }}
  sink "file" {{
    config = {{
      path = "/tmp/vault-token"
    }}
  }}
}}

template {{
  destination = "/shared/secrets.env"
  perms       = "0444"
  contents    = <<-EOT
{template_contents}
  EOT
}}
"""


def generate_policy_hcl(
    *,
    secret_names: list[str],
    workspace_agent_name: str | None = None,
) -> str:
    """Vault policy granting `read` on each listed secret's KV v2 data path.

    When ``workspace_agent_name`` is set, also grant read on every key
    under ``secret/data/_vystak/workspace-ssh/<agent_name>/*`` so the
    vault-agent sidecar can render SSH host/client keys into /shared/.
    """
    paths = []
    for name in secret_names:
        paths.append(
            f'path "secret/data/{name}" {{\n  capabilities = ["read"]\n}}'
        )
    if workspace_agent_name:
        paths.append(
            f'path "secret/data/_vystak/workspace-ssh/{workspace_agent_name}/*"'
            f" {{\n  capabilities = [\"read\"]\n}}"
        )
    return "\n".join(paths)


def generate_agent_hcl_with_workspace_ssh(
    *,
    vault_address: str,
    secret_names: list[str],
    agent_name: str,
    role: str,  # "agent" or "workspace"
) -> str:
    """Extended Vault Agent HCL: user-secret env template + SSH key file
    templates for the agent↔workspace channel."""
    base = generate_agent_hcl(
        vault_address=vault_address, secret_names=secret_names
    )

    if role == "agent":
        # Destinations are under /shared/ssh rather than /vystak/ssh: the
        # vault-agent sidecar writes into the agent-secrets volume mounted
        # at /shared (same volume used by /shared/secrets.env). The agent
        # container's Dockerfile symlinks /vystak/ssh → /shared/ssh so
        # agent-side code can reference the canonical /vystak/ssh/* paths.
        ssh_templates = f"""
template {{
  destination = "/shared/ssh/id_ed25519"
  perms       = "0400"
  contents    = <<-EOT
    {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/client-key" }}}}{{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}

template {{
  destination = "/shared/ssh/known_hosts"
  perms       = "0444"
  contents    = <<-EOT
    vystak-{agent_name}-workspace {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/host-key-pub" }}}} {{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}
"""
    elif role == "workspace":
        ssh_templates = f"""
template {{
  destination = "/shared/ssh_host_ed25519_key"
  perms       = "0600"
  contents    = <<-EOT
    {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/host-key" }}}}{{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}

template {{
  destination = "/shared/authorized_keys_vystak-agent"
  perms       = "0444"
  contents    = <<-EOT
    {{{{- with secret "secret/data/_vystak/workspace-ssh/{agent_name}/client-key-pub" }}}}{{{{ .Data.data.value }}}}{{{{- end }}}}
  EOT
}}
"""
    else:
        raise ValueError(f"role must be 'agent' or 'workspace', got {role!r}")

    return base + ssh_templates


def generate_entrypoint_shim() -> str:
    """Shell script that waits for /shared/secrets.env, sources it into env,
    then execs the main process.

    ``secrets.env`` may be empty (principals with no declared user secrets
    still get a rendered-but-blank file from the Vault Agent template). The
    shim waits for file *existence*, not non-empty, and sources only when
    there are values to source. A small settle delay lets sibling templates
    (e.g. SSH host key for workspace containers) finish rendering before the
    main process starts.
    """
    return """\
#!/bin/sh
# vystak entrypoint shim — waits for Vault Agent to render secrets, then exec
set -e

SECRETS_FILE="/shared/secrets.env"

for i in $(seq 1 30); do
  [ -e "$SECRETS_FILE" ] && break
  sleep 1
done

if [ ! -e "$SECRETS_FILE" ]; then
  echo "vystak: $SECRETS_FILE never populated — Vault Agent unhealthy?" >&2
  exit 1
fi

# Settle: give sibling templates (SSH keys, etc.) a moment to finish.
sleep 1

if [ -s "$SECRETS_FILE" ]; then
  set -a
  . "$SECRETS_FILE"
  set +a
fi

exec "$@"
"""
