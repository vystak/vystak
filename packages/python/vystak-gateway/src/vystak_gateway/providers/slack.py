"""Slack Socket Mode channel provider."""

import httpx
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from vystak_gateway.providers.base import ChannelProviderRunner
from vystak_gateway.router import Router


def _build_session_id(
    provider_name: str,
    channel: str | None,
    thread_ts: str | None = None,
    ts: str | None = None,
    user_id: str | None = None,
) -> str:
    if channel is None and user_id:
        return f"slack:{provider_name}:dm:{user_id}"
    if thread_ts:
        return f"slack:{provider_name}:{channel}:{thread_ts}"
    return f"slack:{provider_name}:{channel}:{ts}"


class SlackProviderRunner(ChannelProviderRunner):
    """Manages a Slack Socket Mode connection."""

    def __init__(self, name: str, config: dict, event_router: Router):
        self.name = name
        self._router = event_router
        self._running = False
        self._app = AsyncApp(token=config["bot_token"])
        self._handler = AsyncSocketModeHandler(self._app, config["app_token"])
        self._setup_listeners()

    def _setup_listeners(self):
        @self._app.event("message")
        async def on_message(event, say):
            await self._handle_message(event, say)

        @self._app.event("app_mention")
        async def on_mention(event, say):
            await self._handle_mention(event, say)

    async def _handle_message(self, event: dict, say) -> None:
        if event.get("bot_id") or event.get("subtype"):
            return

        channel = event.get("channel", "")
        is_dm = event.get("channel_type") == "im"

        route = self._router.resolve(self.name, channel if not is_dm else None, is_dm=is_dm)
        if route is None:
            return

        if not is_dm and route.listen == "mentions":
            return

        await self._forward_and_reply(event, route, say)

    async def _handle_mention(self, event: dict, say) -> None:
        channel = event.get("channel", "")
        route = self._router.resolve(self.name, channel, is_dm=False)
        if route is None:
            return
        await self._forward_and_reply(event, route, say)

    async def _forward_and_reply(self, event: dict, route, say) -> None:
        is_dm = event.get("channel_type") == "im"
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts")
        ts = event.get("ts")
        user_id = event.get("user")

        session_id = _build_session_id(
            self.name,
            channel if not is_dm else None,
            thread_ts=thread_ts,
            ts=ts,
            user_id=user_id if is_dm else None,
        )

        text = event.get("text", "")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{route.agent_url}/invoke",
                json={"message": text, "session_id": session_id},
            )

        if response.status_code == 200:
            data = response.json()
            reply_text = data.get("response", "")
            reply_kwargs = {"text": reply_text}
            if route.threads and not is_dm:
                reply_kwargs["thread_ts"] = thread_ts or ts
            await say(**reply_kwargs)

    async def start(self) -> None:
        self._running = True
        await self._handler.start_async()

    async def stop(self) -> None:
        self._running = False
        await self._handler.close_async()

    def is_running(self) -> bool:
        return self._running
