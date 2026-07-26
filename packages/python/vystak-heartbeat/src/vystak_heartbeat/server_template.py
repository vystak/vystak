"""Build-time artifacts for the vystak-heartbeat container."""

from __future__ import annotations

REQUIREMENTS = """\
httpx>=0.27
aiosqlite>=0.20
asyncpg>=0.29
pydantic>=2.0
pyyaml>=6.0
nats-py>=2.6
croniter>=2.0
psycopg[binary]>=3.0
fastapi>=0.110
uvicorn>=0.29
opentelemetry-api>=1.27
opentelemetry-sdk>=1.27
opentelemetry-exporter-otlp-proto-grpc>=1.27
"""

DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /etc/vystak /data
COPY . .
RUN cp service_config.json routes.json /etc/vystak/ 2>/dev/null || true
ENV VYSTAK_CONFIG_DIR=/etc/vystak PYTHONPATH=/app
CMD python -m vystak_heartbeat
"""
