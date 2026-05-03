"""Build-time artifacts for the Discord channel container."""

from __future__ import annotations

from importlib.metadata import version


def package_version() -> str:
    try:
        return version("vystak-channel-discord")
    except Exception:
        return "0.1.0"


REQUIREMENTS = f"vystak-channel-discord=={package_version()}\n"

DOCKERFILE = f"""\
FROM python:3.11-slim
RUN pip install --no-cache-dir vystak-channel-discord=={package_version()}
COPY channel_config.json routes.json /etc/vystak/
ENV VYSTAK_CONFIG_DIR=/etc/vystak
ENTRYPOINT ["python", "-m", "vystak_channel_discord"]
"""
