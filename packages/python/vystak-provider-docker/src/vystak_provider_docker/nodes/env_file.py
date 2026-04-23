"""DockerEnvFileNode — per-principal env file generation for the default
(no-Vault) delivery path.

For each principal, writes `.vystak/env/<principal>.env` containing only the
secrets declared on that principal, resolved from deployer-supplied env values
(typically from `.env`). The file is chmod 600 and gitignored via `.vystak/`.

The generated env dict is also returned in the provision result so downstream
container nodes can pass it directly to docker-py `environment=` without
re-reading the file.
"""

from pathlib import Path

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class DockerEnvFileNode(Provisionable):
    """Generates a per-principal env file + env dict for the default path."""

    def __init__(
        self,
        *,
        principal_name: str,
        declared_secret_names: list[str],
        env_values: dict[str, str],
        allow_missing: bool = False,
    ):
        self._principal = principal_name
        self._declared = list(declared_secret_names)
        self._env = dict(env_values)
        self._allow_missing = allow_missing

    @property
    def name(self) -> str:
        return f"env-file:{self._principal}"

    @property
    def depends_on(self) -> list[str]:
        return []

    def provision(self, context: dict) -> ProvisionResult:
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for key in self._declared:
            if key in self._env:
                resolved[key] = self._env[key]
            else:
                missing.append(key)

        if missing and not self._allow_missing:
            return ProvisionResult(
                name=self.name,
                success=False,
                error=(
                    f"Secrets declared on principal '{self._principal}' but "
                    f"missing from .env: {', '.join(missing)}. Set them in "
                    f".env, remove from the declaration, or run apply with "
                    f"--allow-missing."
                ),
            )

        env_file_path: str | None = None
        if resolved:
            out_dir = Path(".vystak") / "env"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{self._principal}.env"
            lines = [f"{k}={v}" for k, v in resolved.items()]
            out_file.write_text("\n".join(lines) + "\n")
            out_file.chmod(0o600)
            env_file_path = str(out_file)

        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "env": resolved,
                "env_file_path": env_file_path,
                "missing": missing,
            },
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        """Best-effort removal of the env file; leave the directory."""
        out_file = Path(".vystak") / "env" / f"{self._principal}.env"
        if out_file.exists():
            out_file.unlink()
