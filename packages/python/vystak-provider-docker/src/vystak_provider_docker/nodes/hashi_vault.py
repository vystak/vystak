"""Vault server container + init + unseal provisioning nodes."""

import contextlib
import json
import time
from pathlib import Path

import docker.errors
from vystak.provisioning.node import Provisionable, ProvisionResult

VAULT_CONTAINER_NAME = "vystak-vault"
VAULT_DATA_VOLUME = "vystak-vault-data"


class HashiVaultServerNode(Provisionable):
    """Starts the Vault server container (reuses existing if already running)."""

    def __init__(self, *, client, image: str, port: int, host_port: int | None):
        self._client = client
        self._image = image
        self._port = port
        self._host_port = host_port

    @property
    def name(self) -> str:
        return "hashi-vault:server"

    @property
    def depends_on(self) -> list[str]:
        return ["network"]

    def provision(self, context: dict) -> ProvisionResult:
        # Reuse if already running
        try:
            existing = self._client.containers.get(VAULT_CONTAINER_NAME)
            if existing.status == "running":
                return ProvisionResult(
                    name=self.name,
                    success=True,
                    info={
                        "container_name": VAULT_CONTAINER_NAME,
                        "vault_address": f"http://{VAULT_CONTAINER_NAME}:{self._port}",
                        "reused": True,
                    },
                )
            existing.remove()
        except docker.errors.NotFound:
            pass

        # Ensure data volume (idempotent — docker create is a no-op if the
        # named volume already exists, so we don't need to pre-check).
        with contextlib.suppress(docker.errors.APIError):
            self._client.volumes.create(name=VAULT_DATA_VOLUME)

        network = context["network"].info["network"]

        ports = {}
        if self._host_port:
            ports[f"{self._port}/tcp"] = self._host_port

        # Generate server config into a tmp host file, mount into container
        # Simpler: pass via CMD with inline config for dev, or bake config
        # into the image. We use a bind-mount of a generated config file.
        config_dir = Path(".vystak") / "vault"
        config_dir.mkdir(parents=True, exist_ok=True)
        from vystak_provider_docker.templates import generate_server_hcl

        (config_dir / "vault.hcl").write_text(generate_server_hcl(port=self._port))

        self._client.containers.run(
            image=self._image,
            name=VAULT_CONTAINER_NAME,
            detach=True,
            command=["vault", "server", "-config=/vault/config/vault.hcl"],
            network=network.name,
            ports=ports,
            volumes={
                VAULT_DATA_VOLUME: {"bind": "/vault/file", "mode": "rw"},
                str(config_dir.absolute()): {"bind": "/vault/config", "mode": "ro"},
            },
            cap_add=["IPC_LOCK"],
            labels={"vystak.vault": "server"},
        )

        # Poll for readiness (Vault listening on its port). Break on the
        # first successful lookup of a running container, or on NotFound
        # (e.g. in test doubles that don't track containers.run calls).
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                container = self._client.containers.get(VAULT_CONTAINER_NAME)
            except docker.errors.NotFound:
                break
            if container.status == "running":
                break
            time.sleep(0.5)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "container_name": VAULT_CONTAINER_NAME,
                "vault_address": f"http://{VAULT_CONTAINER_NAME}:{self._port}",
                "reused": False,
            },
        )

    def destroy(self) -> None:
        # Only called on --delete-vault; regular destroy doesn't reach here.
        try:
            container = self._client.containers.get(VAULT_CONTAINER_NAME)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass
        try:
            vol = self._client.volumes.get(VAULT_DATA_VOLUME)
            vol.remove()
        except docker.errors.NotFound:
            pass


class HashiVaultInitNode(Provisionable):
    """Runs vault operator init if not already initialized; persists result
    to .vystak/vault/init.json (chmod 600)."""

    def __init__(
        self,
        *,
        vault_client,
        key_shares: int,
        key_threshold: int,
        init_path: Path,
    ):
        self._vault = vault_client
        self._key_shares = key_shares
        self._key_threshold = key_threshold
        self._init_path = Path(init_path)

    @property
    def name(self) -> str:
        return "hashi-vault:init"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:server"]

    def provision(self, context: dict) -> ProvisionResult:
        # Wait for Vault to be reachable (sys/init endpoint available)
        deadline = time.time() + 30
        last_err = None
        while time.time() < deadline:
            try:
                already_init = self._vault.is_initialized()
                break
            except Exception as e:
                last_err = e
                time.sleep(1)
        else:
            raise RuntimeError(f"Vault not reachable after 30s: {last_err}")

        if already_init:
            if not self._init_path.exists():
                raise RuntimeError(
                    f"Vault is initialized but {self._init_path} is missing. "
                    f"state mismatch — run 'vystak destroy --delete-vault' and retry."
                )
            data = json.loads(self._init_path.read_text())
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "root_token": data["root_token"],
                    "unseal_keys": data["unseal_keys_b64"],
                    "already_initialized": True,
                },
            )

        # Run init
        result = self._vault.initialize(
            key_shares=self._key_shares, key_threshold=self._key_threshold
        )

        import datetime

        self._init_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "unseal_keys_b64": result.unseal_keys,
            "root_token": result.root_token,
            "init_time": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        }
        self._init_path.write_text(json.dumps(payload, indent=2))
        self._init_path.chmod(0o600)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "root_token": result.root_token,
                "unseal_keys": result.unseal_keys,
                "already_initialized": False,
            },
        )

    def destroy(self) -> None:
        pass  # init.json removal handled by --delete-vault flag in provider


class HashiVaultUnsealNode(Provisionable):
    """Unseals Vault using the first N of threshold unseal keys."""

    def __init__(self, *, vault_client, unseal_keys: list[str], key_threshold: int):
        self._vault = vault_client
        self._keys = unseal_keys
        self._threshold = key_threshold

    @property
    def name(self) -> str:
        return "hashi-vault:unseal"

    @property
    def depends_on(self) -> list[str]:
        return ["hashi-vault:init"]

    def provision(self, context: dict) -> ProvisionResult:
        if not self._vault.is_sealed():
            return ProvisionResult(
                name=self.name, success=True, info={"already_unsealed": True}
            )
        self._vault.unseal(self._keys[: self._threshold])
        return ProvisionResult(name=self.name, success=True, info={"already_unsealed": False})

    def destroy(self) -> None:
        pass
