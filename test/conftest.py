"""Shared across the offline and live suites."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixture():
    """Load a captured TikTok payload by name: fixture("video_items")."""
    def load(name):
        path = FIXTURES / f"{name}.json"
        if not path.is_file():
            pytest.fail(f"missing fixture {path.name}; "
                        f"regenerate with: .venv/bin/python test/capture_fixtures.py")
        return json.loads(path.read_text())
    return load


class FakeSession:
    """Stands in for BrowserSession at the only two methods resources call.

    Records every call so a test can assert the endpoint path, item_key and id_key a
    resource asked for - the wiring that breaks silently when TikTok moves an endpoint.
    """

    def __init__(self, *, inline=None, items=None, headless=True):
        self.inline = inline or {}
        self.items = items or []
        self.headless = headless
        self.page = None
        self.calls = []

    async def inline_data(self, url):
        self.calls.append(("inline_data", url))
        return self.inline

    async def harvest(self, url, path, limit, *, item_key="itemList", id_key="id",
                      scroll=True, idle_limit=4, prepare=None):
        self.calls.append(("harvest", url, path, limit, item_key, id_key))
        return self.items[:limit]

    async def settle(self, url):
        self.calls.append(("settle", url))
        return ""

    def log(self, message):
        self.calls.append(("log", message))

    def harvest_call(self):
        """The single harvest call, for tests that make exactly one."""
        calls = [c for c in self.calls if c[0] == "harvest"]
        assert len(calls) == 1, f"expected one harvest, got {len(calls)}"
        return calls[0]


@pytest.fixture
def fake_client():
    """A real TikTokWeb with a fake session - constructing it opens nothing."""
    from tiktokweb import TikTokWeb

    def build(**kwargs):
        session = FakeSession(**kwargs)
        client = TikTokWeb(verbose=False)
        client.session = session
        return client, session
    return build
