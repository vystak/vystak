"""Chat channel container entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from vystak_channel_runtime import launch

from vystak_channel_chat.runtime import ChatChannelRuntime


def main() -> None:
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    config = json.loads((cfg_dir / "channel_config.json").read_text())
    routes_path = cfg_dir / "routes.json"
    routes = json.loads(routes_path.read_text()) if routes_path.exists() else {}
    launch(ChatChannelRuntime, config=config, routes=routes)


if __name__ == "__main__":
    main()
