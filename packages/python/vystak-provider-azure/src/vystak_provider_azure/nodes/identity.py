"""UserAssignedIdentityNode — creates a UAMI or references an existing one."""

from typing import Self

from vystak.provisioning.health import HealthCheck, NoopHealthCheck
from vystak.provisioning.node import Provisionable, ProvisionResult


class UserAssignedIdentityNode(Provisionable):
    """Creates a new UAMI or returns metadata for an existing one.

    The UAMI is intended for use with ACA `identitySettings[].lifecycle: None`
    so the identity's token is never reachable from container code.
    """

    def __init__(
        self,
        client,
        rg_name: str,
        uami_name: str,
        location: str,
        tags: dict | None = None,
    ):
        self._client = client
        self._rg_name = rg_name
        self._uami_name = uami_name
        self._location = location
        self._tags = tags or {}
        self._existing_resource_id: str | None = None

    @classmethod
    def from_existing(cls, *, resource_id: str, name: str) -> Self:
        """Wrap an existing UAMI resource ID — no API calls made."""
        inst = cls.__new__(cls)
        inst._client = None
        inst._rg_name = ""
        inst._uami_name = name
        inst._location = ""
        inst._tags = {}
        inst._existing_resource_id = resource_id
        return inst

    @property
    def name(self) -> str:
        return f"uami:{self._uami_name}"

    def provision(self, context: dict) -> ProvisionResult:
        if self._existing_resource_id:
            return ProvisionResult(
                name=self.name,
                success=True,
                info={
                    "resource_id": self._existing_resource_id,
                    "client_id": None,
                    "principal_id": None,
                    "pre_existing": True,
                },
            )

        from azure.mgmt.msi.models import Identity

        result = self._client.user_assigned_identities.create_or_update(
            resource_group_name=self._rg_name,
            resource_name=self._uami_name,
            parameters=Identity(location=self._location, tags=self._tags),
        )
        return ProvisionResult(
            name=self.name,
            success=True,
            info={
                "resource_id": result.id,
                "client_id": result.client_id,
                "principal_id": result.principal_id,
                "pre_existing": False,
            },
        )

    def health_check(self) -> HealthCheck:
        return NoopHealthCheck()

    def destroy(self) -> None:
        if self._existing_resource_id is not None:
            return
        import contextlib

        with contextlib.suppress(Exception):
            self._client.user_assigned_identities.delete(self._rg_name, self._uami_name)
