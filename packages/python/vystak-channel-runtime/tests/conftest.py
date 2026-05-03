"""Shared test fixtures for vystak-channel-runtime."""

import os

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def postgres_dsn():
    """Postgres DSN for docker-marked tests.

    Docker test job sets POSTGRES_DSN; tests skip if absent.
    """
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        pytest.skip("POSTGRES_DSN not set")
    return dsn
