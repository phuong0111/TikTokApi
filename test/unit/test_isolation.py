"""The guard that makes `test/unit` genuinely offline.

Without this, a unit test that accidentally reaches the network would quietly go
live and pass, which is the exact failure mode this suite exists to rule out.
"""

import socket

import pytest

from tiktokweb import browser, cookies


def test_opening_a_socket_raises():
    with pytest.raises(RuntimeError, match="offline"):
        socket.create_connection(("www.tiktok.com", 443), timeout=1)


def test_socket_connect_raises():
    sock = socket.socket()
    with pytest.raises(RuntimeError, match="offline"):
        sock.connect(("www.tiktok.com", 443))


def test_launching_a_browser_from_browser_module_raises():
    with pytest.raises(RuntimeError, match="offline"):
        browser.async_playwright()


def test_launching_a_browser_from_cookies_module_raises():
    with pytest.raises(RuntimeError, match="offline"):
        cookies.async_playwright()
