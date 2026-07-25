"""Agent entrypoint. User-owned: customize freely.
Imports from _vystak.runtime to build the FastAPI app."""

from _vystak.runtime.app_factory import build_agent_app
from _vystak.runtime.config import load_agent

agent = load_agent("vystak.py")
app = build_agent_app(agent)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
