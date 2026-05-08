"""Template registry — bundled wheel path + dev sibling fallback."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TemplateInfo:
    name: str
    version: str
    path: Path


def _bundled_dir() -> Path | None:
    """Path to vystak_cli/templates/ inside the installed CLI wheel."""
    import vystak_cli
    cli_root = Path(vystak_cli.__file__).parent
    bundled = cli_root / "templates"
    return bundled if bundled.exists() else None


def _dev_workspace_dir() -> Path | None:
    """Path to packages/python/ in editable workspace install.

    Walks up from <install>/vystak-cli/src/vystak_cli/__init__.py:
        cli_root        = <install>/vystak-cli/src/vystak_cli/
        cli_root.parent = <install>/vystak-cli/src/
        ...parent       = <install>/vystak-cli/
        ...parent       = <install>/  (the python/ workspace)
    """
    import vystak_cli
    cli_root = Path(vystak_cli.__file__).parent
    pkg_dir = cli_root.parent.parent  # <workspace>/vystak-cli/
    if pkg_dir.name == "vystak-cli":
        workspace = pkg_dir.parent
        if (
            workspace.name == "python"
            and (workspace / "vystak-template-langchain-python").exists()
        ):
            return workspace
    return None


def list_templates() -> list[TemplateInfo]:
    bundled = _bundled_dir()
    if bundled:
        return _scan_bundled(bundled)
    dev = _dev_workspace_dir()
    if dev:
        return _scan_dev(dev)
    return []


def _scan_bundled(root: Path) -> list[TemplateInfo]:
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "_vystak" / "manifest.template.json").exists():
            seed = json.loads((child / "_vystak" / "manifest.template.json").read_text())
            out.append(TemplateInfo(
                name=seed["template"]["name"],
                version=seed["template"]["version"],
                path=child,
            ))
    return out


def _scan_dev(workspace: Path) -> list[TemplateInfo]:
    out = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or not child.name.startswith("vystak-template-"):
            continue
        seed_path = child / "_vystak" / "manifest.template.json"
        if seed_path.exists():
            seed = json.loads(seed_path.read_text())
            out.append(TemplateInfo(
                name=seed["template"]["name"],
                version=seed["template"]["version"],
                path=child,
            ))
    return out


def resolve_template(name: str) -> TemplateInfo:
    for info in list_templates():
        if info.name == name:
            return info
    raise ValueError(
        f"Unknown framework: {name!r}. Run `vystak init --list-frameworks` to see registry."
    )
