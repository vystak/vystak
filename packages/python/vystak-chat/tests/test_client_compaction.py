from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_compact_posts_with_instructions():
    from vystak_chat import client as c

    with patch("vystak_chat.client.httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.post.return_value.status_code = 200
        instance.post.return_value.json = lambda: {
            "thread_id": "t1",
            "generation": 1,
            "summary_preview": "…",
            "messages_compacted": 12,
        }
        mock_cls.return_value.__aenter__.return_value = instance

        result = await c.compact("http://x:8000", thread_id="t1", instructions="focus on names")

    assert result["generation"] == 1
    posted_url = instance.post.call_args[0][0]
    assert "/v1/sessions/t1/compact" in posted_url
    assert instance.post.call_args.kwargs["json"]["instructions"] == "focus on names"


@pytest.mark.asyncio
async def test_list_compactions_returns_rows():
    from vystak_chat import client as c

    with patch("vystak_chat.client.httpx.AsyncClient") as mock_cls:
        instance = AsyncMock()
        instance.get.return_value.status_code = 200
        instance.get.return_value.json = lambda: {
            "thread_id": "t1",
            "compactions": [{"generation": 2}, {"generation": 1}],
        }
        mock_cls.return_value.__aenter__.return_value = instance

        result = await c.list_compactions("http://x:8000", thread_id="t1")

    assert [r["generation"] for r in result] == [2, 1]
