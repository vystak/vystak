from unittest.mock import AsyncMock, patch

import pytest
from vystak_chat.chat import COMMANDS, ChatREPL


def test_compact_in_command_table():
    cmds = {c[0] for c in COMMANDS}
    assert "/compact" in cmds
    assert "/compactions" in cmds


@pytest.mark.asyncio
async def test_cmd_compact_resolves_thread_and_calls_client():
    repl = ChatREPL()
    repl._agent_url = "http://x:8000"
    repl._agent_name = "agent-x"
    repl._previous_response_id = "resp-abc"

    get_resp_mock = AsyncMock(return_value={"thread_id": "t1"})
    compact_mock = AsyncMock(
        return_value={"generation": 1, "summary_preview": "…", "messages_compacted": 5}
    )
    with patch("vystak_chat.chat.client.get_response", new=get_resp_mock), \
         patch("vystak_chat.chat.client.compact", new=compact_mock) as mock_compact:
        await repl._cmd_compact("focus on names")

    mock_compact.assert_called_once()
    assert mock_compact.call_args.kwargs["thread_id"] == "t1"
    assert mock_compact.call_args.kwargs["instructions"] == "focus on names"


@pytest.mark.asyncio
async def test_cmd_compact_warns_when_no_session():
    repl = ChatREPL()
    repl._agent_url = "http://x:8000"
    # no _previous_response_id
    await repl._cmd_compact("")  # must not raise
