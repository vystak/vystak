"""vystak update — refresh _vystak/ to bundled template version."""

import json
import shutil
from pathlib import Path

import click

from vystak_cli.manifest import _hash_tree
from vystak_cli.templates import resolve_template


def update_command(
    target: str = ".",
    *,
    check: bool = False,
    force: bool = False,
    strict: bool = False,
) -> int:
    """Refresh the project's _vystak/ tree to the bundled CLI's template version.

    Returns 0 if the project is in-sync (or the update succeeded), non-zero
    otherwise (in --check mode).
    """
    target_path = Path(target).resolve()
    manifest_path = target_path / "_vystak" / "manifest.json"
    yaml_path = target_path / "vystak.yaml"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"_vystak/manifest.json not found at {target_path}. "
            "Run vystak init first."
        )

    current = json.loads(manifest_path.read_text())
    current_template_name = current["template"]["name"]
    current_version = current["template"]["version"]

    # Resolve framework from vystak.yaml; refuse to silently switch frameworks.
    if yaml_path.exists():
        framework_in_yaml = _read_framework(yaml_path)
        if framework_in_yaml and framework_in_yaml != current_template_name:
            raise ValueError(
                f"framework in vystak.yaml ({framework_in_yaml}) does not match "
                f"_vystak/manifest.json template.name ({current_template_name}). "
                f"Run: vystak init --framework {framework_in_yaml} --force ."
            )

    info = resolve_template(current_template_name)
    _check_compat(info, strict=strict)
    bundled_version = info.version

    current_hashes = current.get("files", {})
    bundled_hashes = _hash_tree(info.path / "_vystak")
    bundled_hashes_normalized = {
        k.replace("src_template/", ""): v for k, v in bundled_hashes.items()
    }

    is_current = (current_version == bundled_version) and not _hashes_differ(
        current_hashes, bundled_hashes_normalized
    )

    if check:
        click.echo(
            f"current={current_version}, bundled={bundled_version}, "
            f"in_sync={is_current}"
        )
        return 0 if is_current else 1

    if is_current and not force:
        click.echo(f"_vystak/ is current ({current_version}). Use --force to re-stamp.")
        return 0

    cli_version = _cli_version()
    _refresh_vystak_dir(info.path, target_path, cli_version=cli_version)
    click.echo(f"Updated _vystak/ from {current_version} -> {bundled_version}.")
    return 0


def _refresh_vystak_dir(source: Path, target: Path, *, cli_version: str) -> None:
    """Refresh ONLY the managed _vystak/ namespace; never touch user-owned files.

    User-owned files (vystak.yaml, server.py, Dockerfile, requirements.txt,
    tools/, .env.example, README.md, pyproject.toml) are preserved. Only the
    _vystak/ directory contents are replaced and the manifest re-stamped.
    """
    import hashlib
    import json
    from datetime import UTC, datetime

    src_vystak = source / "_vystak"
    dst_vystak = target / "_vystak"

    shutil.rmtree(dst_vystak, ignore_errors=True)
    shutil.copytree(
        src_vystak,
        dst_vystak,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    seed = json.loads((dst_vystak / "manifest.template.json").read_text())
    files: dict[str, str] = {}
    for path in dst_vystak.rglob("*"):
        if not path.is_file() or path.name == "manifest.json":
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(target).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[rel] = f"sha256:{digest}"

    manifest = {
        "schema_version": 1,
        "template": seed["template"],
        "vystak": seed["vystak"],
        "scaffolded_at": datetime.now(UTC).isoformat(),
        "scaffolded_by_cli": cli_version,
        "files": files,
    }
    (dst_vystak / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _read_framework(yaml_path: Path) -> str | None:
    import yaml

    data = yaml.safe_load(yaml_path.read_text())
    return data.get("framework") if isinstance(data, dict) else None


def _hashes_differ(a: dict[str, str], b: dict[str, str]) -> bool:
    return set(a.items()) != set(b.items())


def _cli_version() -> str:
    try:
        from importlib.metadata import version

        return version("vystak-cli")
    except Exception:  # noqa: BLE001
        return "dev"


def _installed_vystak_version() -> str:
    from importlib.metadata import version

    return version("vystak")


def _max_compat_for(info) -> str:  # noqa: ANN001
    seed = json.loads((info.path / "_vystak" / "manifest.template.json").read_text())
    return seed["vystak"]["max_compat"]


def _min_compat_for(info) -> str:  # noqa: ANN001
    seed = json.loads((info.path / "_vystak" / "manifest.template.json").read_text())
    return seed["vystak"]["min_compat"]


def _semver_major(v: str) -> int:
    return int(v.split(".")[0])


def _check_compat(info, *, strict: bool) -> None:  # noqa: ANN001
    installed = _installed_vystak_version()
    max_v = _max_compat_for(info)
    min_v = _min_compat_for(info)

    major_drift = _semver_major(installed) > _semver_major(max_v) or _semver_major(
        installed
    ) < _semver_major(min_v)
    if major_drift:
        if strict:
            raise RuntimeError(
                f"incompatible: installed vystak={installed} outside template's "
                f"compat range [{min_v}, {max_v}]. See _vystak/CHANGELOG.md."
            )
        print(
            f"WARNING: installed vystak={installed} outside template's compat "
            f"range [{min_v}, {max_v}]. Proceeding anyway."
        )
        return

    if installed != max_v:
        print(f"Note: installed vystak={installed}; template's max_compat={max_v}.")


@click.command()
@click.argument("target", default=".")
@click.option(
    "--check",
    is_flag=True,
    default=False,
    help="Exit 0 if in-sync, 1 otherwise; do not write files.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-stamp _vystak/ even when already in sync.",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Reserved — fail on hash drift in user-modified files.",
)
def update(target: str, check: bool, force: bool, strict: bool) -> None:
    """Refresh _vystak/ from the bundled framework template."""
    try:
        rc = update_command(target=target, check=check, force=force, strict=strict)
    except FileNotFoundError as err:
        click.echo(f"Error: {err}", err=True)
        raise SystemExit(1) from err
    except ValueError as err:
        click.echo(f"Error: {err}", err=True)
        raise SystemExit(1) from err
    if rc != 0:
        raise SystemExit(rc)
