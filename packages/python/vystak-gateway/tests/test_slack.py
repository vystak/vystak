from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vystak_gateway.router import Route, Router
from vystak_gateway.providers.slack import SlackProviderRunner, _build_session_id


class TestBuildSessionId:
    def test_thread(self):
        sid = _build_session_id("my-slack", "#support", thread_ts="1234.5678", ts="9999.0000")
        assert sid == "slack:my-slack:#support:1234.5678"

    def test_new_message(self):
        sid = _build_session_id("my-slack", "#support", thread_ts=None, ts="9999.0000")
        assert sid == "slack:my-slack:#support:9999.0000"

    def test_dm(self):
        sid = _build_session_id("my-slack", None, thread_ts=None, ts="9999.0000", user_id="U123")
        assert sid == "slack:my-slack:dm:U123"


class TestSlackProviderRunner:
    @patch("vystak_gateway.providers.slack.AsyncApp")
    @patch("vystak_gateway.providers.slack.AsyncSocketModeHandler")
    def test_create(self, mock_handler_cls, mock_app_cls):
        router = Router()
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )
        assert runner.name == "test-slack"
        assert runner.is_running() is False


@pytest.mark.asyncio
class TestSlackEventHandling:
    @patch("vystak_gateway.providers.slack.httpx")
    @patch("vystak_gateway.providers.slack.AsyncApp")
    @patch("vystak_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_message_routed(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        router.add_route(Route(
            provider_name="test-slack", agent_name="support-bot",
            agent_url="http://agent:8000", channels=["#support"],
            listen="messages", threads=True, dm=True,
        ))
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hello!", "session_id": "test"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_httpx.AsyncClient.return_value = mock_client

        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "#support", "ts": "123.456", "user": "U1"},
            say=say,
        )
        mock_client.post.assert_called_once()
        say.assert_called_once()

    @patch("vystak_gateway.providers.slack.httpx")
    @patch("vystak_gateway.providers.slack.AsyncApp")
    @patch("vystak_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_message_ignored_no_route(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )
        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "#random", "ts": "123.456", "user": "U1"},
            say=say,
        )
        say.assert_not_called()

    @patch("vystak_gateway.providers.slack.httpx")
    @patch("vystak_gateway.providers.slack.AsyncApp")
    @patch("vystak_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_dm_routed(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        router.add_route(Route(
            provider_name="test-slack", agent_name="support-bot",
            agent_url="http://agent:8000", channels=["#support"],
            listen="mentions", dm=True,
        ))
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hi!", "session_id": "test"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_httpx.AsyncClient.return_value = mock_client

        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "D123", "ts": "123.456", "user": "U1", "channel_type": "im"},
            say=say,
        )
        mock_client.post.assert_called_once()
        say.assert_called_once()

    @patch("vystak_gateway.providers.slack.httpx")
    @patch("vystak_gateway.providers.slack.AsyncApp")
    @patch("vystak_gateway.providers.slack.AsyncSocketModeHandler")
    async def test_dm_ignored_when_disabled(self, mock_handler_cls, mock_app_cls, mock_httpx):
        router = Router()
        router.add_route(Route(
            provider_name="test-slack", agent_name="support-bot",
            agent_url="http://agent:8000", channels=["#support"],
            listen="mentions", dm=False,
        ))
        runner = SlackProviderRunner(
            name="test-slack",
            config={"bot_token": "xoxb-test", "app_token": "xapp-test"},
            event_router=router,
        )
        say = AsyncMock()
        await runner._handle_message(
            event={"text": "hello", "channel": "D123", "ts": "123.456", "user": "U1", "channel_type": "im"},
            say=say,
        )
        say.assert_not_called()
