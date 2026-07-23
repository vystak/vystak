FROM python:3.12-slim
WORKDIR /app

# The filesystem MCP server runs via `npx` (stdio), so the image needs node.
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

COPY _vystak/requirements.txt /app/_vystak/requirements.txt
RUN pip install -r /app/_vystak/requirements.txt

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
# The agent reads /docs via the MCP filesystem server.
RUN mkdir -p /docs && cp -r sample-docs/. /docs/
CMD ["python", "server.py"]
