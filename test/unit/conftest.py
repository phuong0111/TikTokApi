"""Everything under test/unit runs offline, and that is enforced rather than assumed."""

import socket

import pytest

from tiktokweb import browser, cookies


def _refuse(*args, **kwargs):
    raise RuntimeError(
        "test/unit is offline: a test tried to reach the network or open a browser. "
        "Use a fixture or a fake; live tests belong in test/live with @pytest.mark.live."
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    # both modules bound the name at import time, so patch it where it is looked up
    monkeypatch.setattr(browser, "async_playwright", _refuse)
    monkeypatch.setattr(cookies, "async_playwright", _refuse)
