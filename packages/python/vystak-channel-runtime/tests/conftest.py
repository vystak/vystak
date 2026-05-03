"""Shared test fixtures for vystak-channel-runtime."""

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
