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


def generate_policy_hcl(*, secret_names: list[str]) -> str:
    """Vault policy granting `read` on each listed secret's KV v2 data path."""
    paths = []
    for name in secret_names:
        paths.append(
            f'path "secret/data/{name}" {{\n  capabilities = ["read"]\n}}'
        )
    return "\n".join(paths)


def generate_entrypoint_shim() -> str:
    """Shell script that waits for /shared/secrets.env, sources it into env,
    then execs the main process."""
    return """\
#!/bin/sh
# vystak entrypoint shim — waits for Vault Agent to render secrets, then exec
set -e

SECRETS_FILE="/shared/secrets.env"

for i in $(seq 1 30); do
  [ -s "$SECRETS_FILE" ] && break
  sleep 1
done

if [ ! -s "$SECRETS_FILE" ]; then
  echo "vystak: $SECRETS_FILE never populated — Vault Agent unhealthy?" >&2
  exit 1
fi

set -a
. "$SECRETS_FILE"
set +a

exec "$@"
"""
