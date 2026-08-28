"""The browser-backed suite. Deselected by default; run with `pytest -m live`.

These need a logged-in cookies.json and talk to live TikTok, so they are slow, flaky by
nature, and put rate-limit exposure on the account whose session is in the jar.
"""

import asyncio
import json
from pathlib import Path

import pytest

from tiktokweb import livetest

HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    """Everything in this directory is live, so mark it here rather than per test.

    This hook is global even from a subdirectory conftest - it receives every collected
    item, offline ones included - so the path check is what keeps it from marking the
    whole suite live and deselecting all of it.
    """
    for item in items:
        if HERE in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.live)


@pytest.fixture(scope="session")
def live_results(tmp_path_factory):
    """Run the whole live suite once and index its results by endpoint name.

    livetest keeps ownership of retries, per-case timeouts and fresh-browser-per-case;
    this only reads the report it writes.
    """
    report = tmp_path_factory.mktemp("live") / "results.json"
    asyncio.run(livetest.main(["--json", str(report)]))

    if not report.is_file():
        pytest.fail("livetest wrote no report - seed discovery failed. "
                    "Retry: TikTok is flaky run to run.")

    data = json.loads(report.read_text())
    return {row["name"]: row for row in data["results"]}
