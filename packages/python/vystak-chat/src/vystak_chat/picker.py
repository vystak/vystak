"""Interactive picker — arrow keys to select from a list."""

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout


async def pick(
    title: str, items: list[dict], display_key: str = "label", detail_key: str = "detail"
) -> dict | None:
    """Show an interactive picker. Returns selected item or None if cancelled.

    items: list of dicts, each must have display_key and optionally detail_key.
    """
    if not items:
        return None

    selected = [0]
    result = [None]

    def get_text():
        lines = []
        lines.append(("bold", f"  {title}\n"))
        lines.append(("", "\n"))
        for i, item in enumerate(items):
            label = item.get(display_key, str(item))
            detail = item.get(detail_key, "")
            if i == selected[0]:
                lines.append(("bold fg:cyan", f"  > {label}"))
                if detail:
                    lines.append(("fg:gray", f"  {detail}"))
                lines.append(("", "\n"))
            else:
                lines.append(("fg:white", f"    {label}"))
                if detail:
                    lines.append(("fg:gray", f"  {detail}"))
                lines.append(("", "\n"))
        lines.append(("", "\n"))
        lines.append(("fg:gray", "  ↑↓ navigate  Enter select  Esc cancel"))
        return lines

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        selected[0] = max(0, selected[0] - 1)

    @kb.add("down")
    def _down(event):
        selected[0] = min(len(items) - 1, selected[0] + 1)

    @kb.add("enter")
    def _enter(event):
        result[0] = items[selected[0]]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event):
        result[0] = None
        event.app.exit()

    control = FormattedTextControl(get_text)
    layout = Layout(Window(control))

    app = Application(layout=layout, key_bindings=kb, full_screen=False)
    await app.run_async()

    return result[0]
