"""Build-time artifacts for the Slack channel container.

The runnable code is the `vystak_channel_slack` package itself.
DockerChannelNode bundles that package's source (plus vystak,
vystak-channel-runtime, vystak_transport_*) into the build context via
COPY . .; PYTHONPATH=/app makes them importable. requirements.txt
lists only third-party deps.
"""

from __future__ import annotations

REQUIREMENTS = """\
slack-bolt>=1.21
aiohttp>=3.9
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
pydantic>=2.0
pyyaml>=6.0
aiosqlite>=0.20
asyncpg>=0.29
nats-py>=2.6
psycopg[binary]>=3.0
"""

DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data /etc/vystak
COPY . .
RUN cp channel_config.json routes.json /etc/vystak/ 2>/dev/null || true
ENV VYSTAK_CONFIG_DIR=/etc/vystak PYTHONPATH=/app
CMD ["python", "-m", "vystak_channel_slack"]
"""
