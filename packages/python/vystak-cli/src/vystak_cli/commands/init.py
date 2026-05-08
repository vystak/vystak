"""vystak init — scaffold a new agent project from a framework template."""

from pathlib import Path

import click

from vystak_cli.manifest import scaffold_template
from vystak_cli.templates import list_templates, resolve_template


def init_command(
    target: str,
    framework: str | None = None,
    force: bool = False,
) -> None:
    """Scaffold a new agent project from a framework template."""
    framework = framework or "langchain-python"
    info = resolve_template(framework)

    target_path = Path(target).resolve()
    cli_version = _cli_version()
    scaffold_template(info.path, target_path, cli_version=cli_version, force=force)
    click.echo(f"Scaffolded {framework}@{info.version} into {target_path}")


def list_frameworks_command() -> None:
    """Print bundled frameworks (one per line, name<TAB>version)."""
    for info in list_templates():
        click.echo(f"{info.name}\t{info.version}")


def _cli_version() -> str:
    try:
        from importlib.metadata import version

        return version("vystak-cli")
    except Exception:  # noqa: BLE001
        return "dev"


@click.command()
@click.argument("target", default=".")
@click.option(
    "--framework",
    default=None,
    help="Framework template to scaffold (default: langchain-python).",
)
@click.option(
    "--list-frameworks",
    "list_frameworks",
    is_flag=True,
    default=False,
    help="List bundled framework templates and exit.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing target directory.",
)
def init(target: str, framework: str | None, list_frameworks: bool, force: bool) -> None:
    """Scaffold a new agent project from a framework template."""
    if list_frameworks:
        list_frameworks_command()
        return
    try:
        init_command(target=target, framework=framework, force=force)
    except ValueError as err:
        click.echo(f"Error: {err}", err=True)
        raise SystemExit(1) from err
    except FileExistsError as err:
        click.echo(f"Error: {err}", err=True)
        raise SystemExit(1) from err
