"""Thin wrapper over hvac for Vault init / unseal / AppRole / KV v2 operations.

Exists so provisioning nodes can mock a small, narrow interface instead of
full hvac. Also centralizes idempotency checks (enable-if-missing) and
normalizes KV v2's `{data: {data: {value}}}` path into flat get/put.
"""

import contextlib
from dataclasses import dataclass

import hvac
import hvac.exceptions


@dataclass
class VaultInitResult:
    unseal_keys: list[str]
    root_token: str


class VaultClient:
    """Narrow wrapper around hvac — only the operations vystak uses."""

    def __init__(self, url: str, token: str | None = None):
        self._url = url
        self._client = hvac.Client(url=url, token=token)

    # -- lifecycle --------------------------------------------------------

    def is_initialized(self) -> bool:
        return bool(self._client.sys.is_initialized())

    def is_sealed(self) -> bool:
        return bool(self._client.sys.is_sealed())

    def initialize(self, *, key_shares: int = 5, key_threshold: int = 3) -> VaultInitResult:
        result = self._client.sys.initialize(
            secret_shares=key_shares, secret_threshold=key_threshold
        )
        return VaultInitResult(
            unseal_keys=result["keys_base64"],
            root_token=result["root_token"],
        )

    def unseal(self, keys: list[str]) -> None:
        for key in keys:
            if not self._client.sys.is_sealed():
                break
            self._client.sys.submit_unseal_key(key)

    def set_token(self, token: str) -> None:
        self._client.token = token

    # -- kv v2 / approle setup -------------------------------------------

    def enable_kv_v2(self, mount_path: str = "secret") -> None:
        mounts = self._client.sys.list_mounted_secrets_engines() or {}
        if f"{mount_path}/" in mounts:
            return
        self._client.sys.enable_secrets_engine(
            backend_type="kv", path=mount_path, options={"version": "2"}
        )

    def enable_approle_auth(self) -> None:
        methods = self._client.sys.list_auth_methods() or {}
        if "approle/" in methods:
            return
        self._client.sys.enable_auth_method(method_type="approle")

    # -- policies + approles ---------------------------------------------

    def write_policy(self, name: str, hcl: str) -> None:
        self._client.sys.create_or_update_policy(name=name, policy=hcl)

    def delete_policy(self, name: str) -> None:
        with contextlib.suppress(Exception):
            self._client.sys.delete_policy(name=name)

    def upsert_approle(
        self,
        *,
        role_name: str,
        policies: list[str],
        token_ttl: str = "1h",
        token_max_ttl: str = "24h",
    ) -> tuple[str, str]:
        """Create or update an AppRole and return fresh (role_id, secret_id)."""
        self._client.auth.approle.create_or_update_approle(
            role_name=role_name,
            token_policies=policies,
            token_ttl=token_ttl,
            token_max_ttl=token_max_ttl,
            bind_secret_id=True,
        )
        role_id = self._client.auth.approle.read_role_id(role_name=role_name)["data"]["role_id"]
        secret_id = self._client.auth.approle.generate_secret_id(role_name=role_name)["data"][
            "secret_id"
        ]
        return role_id, secret_id

    def delete_approle(self, role_name: str) -> None:
        with contextlib.suppress(Exception):
            self._client.auth.approle.delete_role(role_name=role_name)

    # -- KV v2 with flat interface ---------------------------------------

    def kv_get(self, name: str) -> str | None:
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(path=name)
        except hvac.exceptions.InvalidPath:
            return None
        return resp["data"]["data"].get("value")

    def kv_put(self, name: str, value: str) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=name, secret={"value": value}
        )

    def kv_list(self) -> list[str]:
        try:
            resp = self._client.secrets.kv.v2.list_secrets(path="")
        except hvac.exceptions.InvalidPath:
            return []
        return resp["data"]["keys"]
