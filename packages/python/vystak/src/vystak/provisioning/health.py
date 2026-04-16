"""Health check classes for resource readiness verification."""

import socket
import time
import urllib.request
from abc import ABC, abstractmethod


class HealthCheck(ABC):
    @abstractmethod
    def check(self) -> bool: ...

    def wait(self, timeout: int = 60, interval: float = 1.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.check():
                return
            time.sleep(interval)
        raise TimeoutError(f"Health check did not pass within {timeout}s")


class NoopHealthCheck(HealthCheck):
    def check(self) -> bool:
        return True


class TcpHealthCheck(HealthCheck):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def check(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            return False


class CommandHealthCheck(HealthCheck):
    def __init__(self, container, command: list[str]):
        self.container = container
        self.command = command

    def check(self) -> bool:
        try:
            result = self.container.exec_run(self.command, demux=False)
            return result.exit_code == 0
        except Exception:
            return False


class HttpHealthCheck(HealthCheck):
    def __init__(self, url: str):
        self.url = url

    def check(self) -> bool:
        try:
            resp = urllib.request.urlopen(self.url, timeout=2)
            return resp.status == 200
        except Exception:
            return False
