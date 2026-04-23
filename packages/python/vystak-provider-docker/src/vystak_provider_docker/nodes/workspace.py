"""DockerWorkspaceNode — builds and runs the workspace container."""

import shutil
from pathlib import Path

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult
from vystak.schema.workspace import Workspace

from vystak_provider_docker.workspace_image import generate_workspace_dockerfile


class DockerWorkspaceNode(Provisionable):
    """Builds the workspace image, runs the container."""

    def __init__(
        self,
        *,
        client,
        agent_name: str,
        workspace: Workspace,
        tools_dir: Path,
    ):
        self._client = client
        self._agent_name = agent_name
        self._workspace = workspace
        self._tools_dir = Path(tools_dir)
        self._default_path_env: dict[str, str] | None = None
        self._default_path_ssh_host_dir: str | None = None

    @property
    def container_name(self) -> str:
        return f"vystak-{self._agent_name}-workspace"

    @property
    def data_volume_name(self) -> str:
        return f"vystak-{self._agent_name}-workspace-data"

    @property
    def secrets_volume_name(self) -> str:
        # The vault-agent sidecar for the workspace principal writes here.
        return f"vystak-{self._agent_name}-workspace-secrets"

    @property
    def name(self) -> str:
        return f"workspace:{self._agent_name}"

    @property
    def depends_on(self) -> list[str]:
        if self._default_path_env is not None:
            # Default path: no Vault Agent sidecar, just the keygen node.
            return [f"workspace-ssh-keygen:{self._agent_name}"]
        return [
            f"vault-agent:{self._agent_name}-workspace",
            f"workspace-ssh-keygen:{self._agent_name}",
        ]

    def set_default_path_context(
        self,
        *,
        env: dict[str, str],
        ssh_host_dir: str,
    ) -> None:
        """Declare the default (no-Vault) delivery context.

        Env dict is passed directly to docker run environment=. SSH host
        directory is bind-mounted piece-by-piece into the workspace's /shared
        path (matching sshd_config expectations for
        /shared/ssh_host_ed25519_key and /shared/authorized_keys_vystak-agent).
        """
        self._default_path_env = dict(env)
        self._default_path_ssh_host_dir = ssh_host_dir

    def provision(self, context: dict) -> ProvisionResult:
        ws = self._workspace
        build_dir = Path(".vystak") / f"{self._agent_name}-workspace"
        build_dir.mkdir(parents=True, exist_ok=True)

        # Generate Dockerfile (unless user provided custom)
        if ws.dockerfile:
            dockerfile_path = Path(ws.dockerfile).resolve()
            shutil.copy(dockerfile_path, build_dir / "Dockerfile")
        else:
            df = generate_workspace_dockerfile(
                image=ws.image,
                provision=ws.provision,
                copy=ws.copy,
                tool_deps_manager=ws.tool_deps_manager,
            )
            (build_dir / "Dockerfile").write_text(df)

        # sshd config (static)
        sshd_conf = self._generate_sshd_config(ws)
        (build_dir / "vystak-sshd.conf").write_text(sshd_conf)

        # entrypoint-shim (reuse v1 pattern)
        from vystak_provider_docker.templates import generate_entrypoint_shim
        (build_dir / "entrypoint-shim.sh").write_text(generate_entrypoint_shim())

        # Copy vystak_workspace_rpc source into build context
        import vystak_workspace_rpc
        src = Path(vystak_workspace_rpc.__file__).parent
        dst = build_dir / "vystak_workspace_rpc"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        # Also ship a minimal setup.py so pip install works
        (build_dir / "setup.py").write_text(
            "from setuptools import setup, find_packages\n"
            "setup(name='vystak-workspace-rpc', version='0.1.0',\n"
            "      packages=find_packages())\n"
        )

        # Tools dir
        tools_dst = build_dir / "tools"
        if tools_dst.exists():
            shutil.rmtree(tools_dst)
        if self._tools_dir.exists():
            shutil.copytree(self._tools_dir, tools_dst)
        else:
            tools_dst.mkdir()

        # Human authorized_keys if ssh=True
        if ws.ssh:
            keys_content = "\n".join(ws.ssh_authorized_keys)
            if ws.ssh_authorized_keys_file:
                keys_content += "\n" + Path(ws.ssh_authorized_keys_file).read_text()
            (build_dir / "human-authorized_keys").write_text(keys_content)

        # Build
        image_tag = f"{self.container_name}:latest"
        self._client.images.build(path=str(build_dir), tag=image_tag, rm=True)

        # Run
        network = context["network"].info["network"]
        # Stop existing
        try:
            existing = self._client.containers.get(self.container_name)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        volumes: dict = {}
        if self._default_path_ssh_host_dir is not None:
            # Default path: bind-mount individual SSH files matching the
            # sshd_config paths (HostKey /shared/ssh_host_ed25519_key;
            # AuthorizedKeysFile /shared/authorized_keys_vystak-agent).
            ssh_dir = Path(self._default_path_ssh_host_dir)
            volumes[str(ssh_dir / "host-key")] = {
                "bind": "/shared/ssh_host_ed25519_key",
                "mode": "ro",
            }
            volumes[str(ssh_dir / "client-key.pub")] = {
                "bind": "/shared/authorized_keys_vystak-agent",
                "mode": "ro",
            }
        else:
            # Vault path: /shared is populated by the workspace-principal
            # Vault Agent sidecar volume.
            volumes[self.secrets_volume_name] = {"bind": "/shared", "mode": "ro"}
        tmpfs: dict = {}
        if ws.persistence == "volume":
            # Ensure data volume exists
            try:
                self._client.volumes.get(self.data_volume_name)
            except docker.errors.NotFound:
                self._client.volumes.create(name=self.data_volume_name)
            volumes[self.data_volume_name] = {"bind": "/workspace", "mode": "rw"}
        elif ws.persistence == "bind":
            host_path = str(Path(ws.path).expanduser().resolve())
            volumes[host_path] = {"bind": "/workspace", "mode": "rw"}
        elif ws.persistence == "ephemeral":
            tmpfs["/workspace"] = "rw,size=512m"

        ports: dict = {}
        if ws.ssh and ws.ssh_host_port:
            ports["22/tcp"] = ws.ssh_host_port
        elif ws.ssh:
            ports["22/tcp"] = None  # Docker auto-allocates

        run_kwargs: dict = dict(
            image=image_tag,
            name=self.container_name,
            detach=True,
            network=network.name,
            volumes=volumes,
            tmpfs=tmpfs,
            ports=ports,
            labels={
                "vystak.workspace": self._agent_name,
                "vystak.workspace.persistence": ws.persistence,
            },
        )
        if self._default_path_env is not None:
            run_kwargs["environment"] = dict(self._default_path_env)

        self._client.containers.run(**run_kwargs)

        info: dict = {
            "container_name": self.container_name,
            "workspace_host": self.container_name,  # internal DNS
            "data_volume_name": (
                self.data_volume_name if ws.persistence == "volume" else None
            ),
        }
        if ws.ssh:
            # Re-fetch container to read the host port assigned by Docker.
            container = self._client.containers.get(self.container_name)
            port_info = container.ports.get("22/tcp")
            if port_info:
                info["ssh_host_port"] = port_info[0]["HostPort"]

        return ProvisionResult(name=self.name, success=True, info=info)

    def _generate_sshd_config(self, ws: Workspace) -> str:
        lines = [
            "HostKey /shared/ssh_host_ed25519_key",
            "Subsystem vystak-rpc /usr/local/bin/vystak-workspace-rpc",
            "PermitRootLogin no",
            "PasswordAuthentication no",
            "PubkeyAuthentication yes",
            "ClientAliveInterval 60",
            "ClientAliveCountMax 3",
            "",
            "Match User vystak-agent",
            "    AuthenticationMethods publickey",
            "    AuthorizedKeysFile /shared/authorized_keys_vystak-agent",
            "    ForceCommand /usr/local/bin/vystak-workspace-rpc",
            "    PermitTTY no",
            "    X11Forwarding no",
            "    AllowTcpForwarding yes",
            "    GatewayPorts no",
            "    PermitOpen any",
        ]
        if ws.ssh:
            lines += [
                "",
                "Match User vystak-dev",
                "    AuthenticationMethods publickey",
                "    AuthorizedKeysFile /etc/vystak-ssh/human-authorized_keys",
                "    X11Forwarding no",
                "    PermitTTY yes",
            ]
        return "\n".join(lines) + "\n"

    def destroy(self) -> None:
        try:
            c = self._client.containers.get(self.container_name)
            c.stop()
            c.remove()
        except docker.errors.NotFound:
            pass
        # Data volume preserved by default; destroy() only called on
        # --delete-workspace-data flag.
