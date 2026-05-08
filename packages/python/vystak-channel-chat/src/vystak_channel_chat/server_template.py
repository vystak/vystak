"""Build-time artifacts for the chat channel container.

The runnable code is the `vystak_channel_chat` package itself.
DockerChannelNode bundles that package's source plus vystak +
vystak-channel-runtime + transports via COPY . .;
PYTHONPATH=/app makes them importable.
"""

from __future__ import annotations

REQUIREMENTS = """\
fastapi>=0.115
uvicorn>=0.34
httpx>=0.28
pydantic>=2.0
pyyaml>=6.0
aiosqlite>=0.20
asyncpg>=0.29
nats-py>=2.6
psycopg[binary]>=3.0
opentelemetry-api>=1.27
opentelemetry-sdk>=1.27
opentelemetry-exporter-otlp-proto-grpc>=1.27
opentelemetry-instrumentation-fastapi>=0.48b0
opentelemetry-instrumentation-httpx>=0.48b0
"""

DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /etc/vystak
COPY . .
RUN cp channel_config.json routes.json /etc/vystak/ 2>/dev/null || true
ENV VYSTAK_CONFIG_DIR=/etc/vystak PYTHONPATH=/app PORT=8080
CMD ["python", "-m", "vystak_channel_chat"]
"""
