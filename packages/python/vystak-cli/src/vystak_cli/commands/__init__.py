"""CLI subcommands.

Note: Click commands are exposed as `<name>_cmd` (e.g. `update_cmd`) so the
bare submodule names (`apply`, `update`, etc.) remain references to the
modules themselves. That keeps `monkeypatch.setattr` paths like
`vystak_cli.commands.update._installed_vystak_version` resolvable in tests:
pytest walks the dotted path with `getattr`, so if `commands.update` were
the Click command the walk would hit a `<Command>` and fail.
"""

from vystak_cli.commands.apply import apply as apply_cmd
from vystak_cli.commands.destroy import destroy as destroy_cmd
from vystak_cli.commands.init import init as init_cmd
from vystak_cli.commands.logs import logs as logs_cmd
from vystak_cli.commands.plan import plan as plan_cmd
from vystak_cli.commands.secrets import secrets as secrets_cmd
from vystak_cli.commands.status import status as status_cmd
from vystak_cli.commands.update import update as update_cmd

__all__ = [
    "apply_cmd",
    "destroy_cmd",
    "init_cmd",
    "logs_cmd",
    "plan_cmd",
    "secrets_cmd",
    "status_cmd",
    "update_cmd",
]
