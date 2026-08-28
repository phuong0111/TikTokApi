"""One test per endpoint, all reading a single live run.

test/live has no __init__.py, so this file cannot import ENDPOINTS from conftest by
relative path; the live_results fixture arrives through pytest's fixture lookup, which
needs no import, and the endpoint names are listed inline for the same reason.
"""

import pytest


@pytest.mark.parametrize("endpoint", [
    "user_info", "user_videos", "video_info", "video_comments", "related_videos",
    "hashtag_videos", "sound_videos", "search_users", "trending",
])
def test_endpoint_returned_data(live_results, endpoint):
    row = live_results.get(endpoint)
    if row is None:
        pytest.skip(f"{endpoint} was not part of this run")

    assert row["status"] == "PASS", (
        f"{endpoint} returned {row['status']} (n={row['n']}). TikTok is flaky run to run "
        f"and livetest already retried; re-check with "
        f"`python -m tiktokweb selftest --only {endpoint} --retries 2`"
    )
    assert row["n"] > 0
