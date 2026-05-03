"""Build-time artifacts for the Slack channel container.

We no longer emit a SERVER_PY string. The container is built from the
installed `vystak-channel-slack` package; its __main__ entrypoint reads
config files mounted into /etc/vystak/.
"""

from __future__ import annotations

from importlib.metadata import version


def package_version() -> str:
    try:
        return version("vystak-channel-slack")
    except Exception:
        return "0.1.0"


REQUIREMENTS = f"vystak-channel-slack=={package_version()}\n"

DOCKERFILE = f"""\
FROM python:3.11-slim
RUN pip install --no-cache-dir vystak-channel-slack=={package_version()}
COPY channel_config.json routes.json /etc/vystak/
ENV VYSTAK_CONFIG_DIR=/etc/vystak
ENTRYPOINT ["python", "-m", "vystak_channel_slack"]
"""
