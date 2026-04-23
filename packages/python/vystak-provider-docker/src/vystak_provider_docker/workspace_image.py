"""Dockerfile generator for workspace containers.

Takes user schema fields (image, provision, copy, tool_deps_manager),
produces the full Dockerfile string. Vystak appendix handles openssh,
vystak-workspace-rpc installation, and — on the Vault path only — an
entrypoint shim that blocks until Vault Agent has rendered
/shared/secrets.env. On the default path, sshd becomes CMD directly.
"""


def detect_tool_deps_manager(image: str) -> str | None:
    """Infer package manager from base image name.

    Heuristic: look for 'python' or 'node' anywhere in the image name
    (covers python:3.12-slim, python:3.12-alpine, cimg/python:3.12, etc.).
    """
    lower = image.lower()
    if "python" in lower:
        return "pip"
    if "node" in lower:
        return "npm"
    return None


def generate_workspace_dockerfile(
    *,
    image: str,
    provision: list[str],
    copy: dict[str, str],
    tool_deps_manager: str | None,
    use_entrypoint_shim: bool = True,
) -> str:
    """Build the workspace Dockerfile. User layers first, vystak layers last.

    ``use_entrypoint_shim`` controls whether the Vault-path entrypoint shim
    (waits for ``/shared/secrets.env`` to appear) is wired in. Set it to
    False on the default (no-Vault) path, where env values are already in
    the container via ``docker run environment=`` and there's nothing to
    wait for — sshd becomes the entrypoint directly.
    """
    effective_manager = tool_deps_manager
    if effective_manager is None:
        effective_manager = detect_tool_deps_manager(image)

    lines = [f"FROM {image}", "WORKDIR /workspace", ""]

    for cmd in provision:
        lines.append(f"RUN {cmd}")
    if provision:
        lines.append("")

    for src, dst in copy.items():
        lines.append(f"COPY {src} {dst}")
    if copy:
        lines.append("")

    # --- Vystak appendix ---
    lines.append("# --- Vystak appendix (do not edit) ---")
    # Claim UIDs 100 (vystak-agent) and 101 (vystak-dev) BEFORE installing
    # openssh-server. Debian slim bases create `sshd` at UID 100 during
    # openssh-server postinst if that UID is free, which would then collide
    # with our useradd. Some bases (e.g. cimg/*) also pre-populate these
    # UIDs — so defensively remove any conflicting user first.
    lines.append(
        "RUN (getent passwd 100 >/dev/null && "
        "userdel -f \"$(getent passwd 100 | cut -d: -f1)\" || true) && "
        "(getent passwd 101 >/dev/null && "
        "userdel -f \"$(getent passwd 101 | cut -d: -f1)\" || true) && "
        "useradd -m -u 100 vystak-agent && "
        "useradd -m -u 101 vystak-dev"
    )
    # openssh-server + vystak-workspace-rpc (installed via pip from bundled source)
    # sshd's own user lands on the next free UID since 100 is now ours.
    lines.append(
        "RUN apt-get update && apt-get install -y --no-install-recommends "
        "openssh-server git ca-certificates python3 python3-pip && "
        "rm -rf /var/lib/apt/lists/* && "
        "mkdir -p /var/run/sshd /vystak/ssh /shared && "
        "chown -R vystak-agent /workspace"
    )
    # sshd config
    lines.append("COPY vystak-sshd.conf /etc/ssh/sshd_config.d/50-vystak.conf")
    # vystak-workspace-rpc: ship setup.py + package dir into one pip-installable tree
    lines.append("COPY setup.py /opt/vystak_workspace_rpc_pkg/setup.py")
    lines.append(
        "COPY vystak_workspace_rpc /opt/vystak_workspace_rpc_pkg/vystak_workspace_rpc"
    )
    lines.append(
        "RUN pip3 install --break-system-packages /opt/vystak_workspace_rpc_pkg && "
        "printf '#!/bin/sh\\nexec python3 -m vystak_workspace_rpc \"$@\"\\n' "
        "> /usr/local/bin/vystak-workspace-rpc && "
        "chmod +x /usr/local/bin/vystak-workspace-rpc"
    )
    # Tools directory
    lines.append("COPY tools/ /workspace/tools/")
    # Tool deps install
    if effective_manager == "pip":
        lines.append(
            "RUN test -f /workspace/tools/requirements.txt && "
            "pip3 install --break-system-packages -r /workspace/tools/requirements.txt "
            "|| true"
        )
    elif effective_manager == "npm":
        lines.append(
            "RUN test -f /workspace/tools/package.json && "
            "(cd /workspace/tools && npm install) || true"
        )
    # Entrypoint — Vault path uses a shim that blocks until
    # /shared/secrets.env is populated; default path runs sshd directly
    # because env is already delivered at container start.
    if use_entrypoint_shim:
        lines.append("COPY entrypoint-shim.sh /vystak/entrypoint-shim.sh")
        lines.append("RUN chmod +x /vystak/entrypoint-shim.sh")
        lines.append('ENTRYPOINT ["/vystak/entrypoint-shim.sh"]')
    lines.append('CMD ["/usr/sbin/sshd", "-D", "-e"]')

    return "\n".join(lines) + "\n"
