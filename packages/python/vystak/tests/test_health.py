# packages/python/vystak/tests/test_health.py
import socket
from unittest.mock import MagicMock, patch

import pytest

from vystak.provisioning.health import (
    CommandHealthCheck,
    HealthCheck,
    HttpHealthCheck,
    NoopHealthCheck,
    TcpHealthCheck,
)


class TestNoopHealthCheck:
    def test_always_ready(self):
        check = NoopHealthCheck()
        assert check.check() is True

    def test_wait_returns_immediately(self):
        check = NoopHealthCheck()
        check.wait(timeout=1)


class TestTcpHealthCheck:
    def test_check_succeeds_when_port_open(self):
        with patch("vystak.provisioning.health.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            check = TcpHealthCheck(host="localhost", port=5432)
            assert check.check() is True

    def test_check_fails_when_port_closed(self):
        with patch("vystak.provisioning.health.socket.create_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError
            check = TcpHealthCheck(host="localhost", port=5432)
            assert check.check() is False

    def test_wait_timeout(self):
        with patch("vystak.provisioning.health.socket.create_connection") as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError
            check = TcpHealthCheck(host="localhost", port=5432)
            with pytest.raises(TimeoutError):
                check.wait(timeout=0.1, interval=0.05)


class TestCommandHealthCheck:
    def test_check_succeeds(self):
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=0)
        check = CommandHealthCheck(container=container, command=["pg_isready"])
        assert check.check() is True

    def test_check_fails(self):
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=1)
        check = CommandHealthCheck(container=container, command=["pg_isready"])
        assert check.check() is False

    def test_check_handles_exception(self):
        container = MagicMock()
        container.exec_run.side_effect = Exception("container not running")
        check = CommandHealthCheck(container=container, command=["pg_isready"])
        assert check.check() is False


class TestHttpHealthCheck:
    def test_check_succeeds(self):
        with patch("vystak.provisioning.health.urllib.request.urlopen") as mock_open:
            mock_open.return_value.status = 200
            check = HttpHealthCheck(url="http://localhost:8000/health")
            assert check.check() is True

    def test_check_fails_on_error(self):
        with patch("vystak.provisioning.health.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = Exception("connection refused")
            check = HttpHealthCheck(url="http://localhost:8000/health")
            assert check.check() is False
