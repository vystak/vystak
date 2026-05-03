"""Slack channel container entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from vystak_channel_runtime import launch

from vystak_channel_slack.runtime import SlackChannelRuntime


def main() -> None:
    cfg_dir = Path(os.environ.get("VYSTAK_CONFIG_DIR", "/etc/vystak"))
    config = json.loads((cfg_dir / "channel_config.json").read_text())
    routes = json.loads((cfg_dir / "routes.json").read_text())
    launch(SlackChannelRuntime, config=config, routes=routes)


if __name__ == "__main__":
    main()
