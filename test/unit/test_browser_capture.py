"""The capture machinery, driven with fakes instead of a browser.

Two of these are regressions for bugs that already bit this repo: _flush dropping
tasks appended while it awaited, and _drain hanging on a body that never completes.
Both look exactly like "TikTok returned nothing", which is why they need tests.
"""

import asyncio
import time

from tiktokweb.browser import BrowserSession


class FakeResponse:
    """Only the two attributes _on_response and _drain actually touch."""

    def __init__(self, url, body):
        self.url = url
        self._body = body

    async def json(self):
        return self._body


class HangingResponse:
    """A body that never completes - the shape that deadlocked a run for 39 minutes."""

    url = "https://www.tiktok.com/api/post/item_list/?count=30"

    async def json(self):
        await asyncio.sleep(30)
        return {}


class BadResponse:
    url = "https://www.tiktok.com/api/post/item_list/?count=30"

    async def json(self):
        raise ValueError("not json")


def make_capture(path="/api/post/item_list", item_key="itemList", id_key="id"):
    return {"path": path, "item_key": item_key, "id_key": id_key,
            "items": [], "seen": set(), "exhausted": False}


def make_session(**kwargs):
    kwargs.setdefault("body_timeout", 1)
    return BrowserSession(**kwargs)


# --------------------------------------------------------------------- _on_response

async def test_on_response_captures_a_matching_path():
    session = make_session()
    capture = make_capture()
    session._captures.append(capture)

    session._on_response(FakeResponse(
        "https://www.tiktok.com/api/post/item_list/?count=30", {"itemList": [{"id": "1"}]}))

    assert len(session._pending) == 1
    await session._flush()
    assert [item["id"] for item in capture["items"]] == ["1"]


async def test_on_response_ignores_an_unregistered_path():
    session = make_session()
    capture = make_capture()
    session._captures.append(capture)

    session._on_response(FakeResponse(
        "https://www.tiktok.com/api/comment/list/?count=20", {"comments": [{"cid": "9"}]}))

    assert session._pending == []
    assert capture["items"] == []


# --------------------------------------------------------------------------- _drain

async def test_drain_dedupes_on_id_key():
    session = make_session()
    capture = make_capture()
    body = {"itemList": [{"id": "1"}, {"id": "2"}, {"id": "1"}]}

    await session._drain(FakeResponse("x/api/post/item_list", body), capture)
    await session._drain(FakeResponse("x/api/post/item_list", body), capture)

    assert [item["id"] for item in capture["items"]] == ["1", "2"]


async def test_drain_falls_back_to_the_whole_item_when_id_key_is_none():
    """Search endpoints pass id_key=None because their hits carry no stable id."""
    session = make_session()
    capture = make_capture(path="/api/search/user", item_key="user_list", id_key=None)
    body = {"user_list": [{"user_info": {"uid": "1"}}, {"user_info": {"uid": "1"}},
                          {"user_info": {"uid": "2"}}]}

    await session._drain(FakeResponse("x/api/search/user", body), capture)

    assert len(capture["items"]) == 2


async def test_drain_marks_exhausted_on_has_more_false():
    session = make_session()
    capture = make_capture()

    await session._drain(FakeResponse("x", {"itemList": [{"id": "1"}], "hasMore": False}), capture)
    assert capture["exhausted"] is True


async def test_drain_leaves_exhausted_alone_while_has_more_is_true():
    session = make_session()
    capture = make_capture()

    await session._drain(FakeResponse("x", {"itemList": [{"id": "1"}], "hasMore": True}), capture)
    assert capture["exhausted"] is False


async def test_drain_is_bounded_by_body_timeout():
    """Regression: response.json() waits forever on a body that never completes."""
    session = make_session(body_timeout=0.05)
    capture = make_capture()

    started = time.monotonic()
    await session._drain(HangingResponse(), capture)

    assert time.monotonic() - started < 5
    assert capture["items"] == []


async def test_drain_swallows_a_non_json_body():
    session = make_session()
    capture = make_capture()

    await session._drain(BadResponse(), capture)
    assert capture["items"] == []


# --------------------------------------------------------------------------- _flush

async def test_flush_keeps_tasks_appended_while_it_was_awaiting():
    """Regression: gather-then-clear drops tasks appended mid-gather.

    That loses captured items silently and reads as an empty endpoint.
    """
    session = make_session()
    drained = []

    async def second():
        # a real await point: this cannot finish opportunistically on the loop cycles
        # left inside _flush, so it completes only if _flush genuinely waits for it
        await asyncio.sleep(0.05)
        drained.append("second")

    async def first():
        drained.append("first")
        session._pending.append(asyncio.create_task(second()))

    session._pending.append(asyncio.create_task(first()))
    await session._flush()

    assert drained == ["first", "second"]
    assert session._pending == []


async def test_flush_returns_immediately_when_nothing_is_pending():
    session = make_session()
    await session._flush()
    assert session._pending == []


async def test_flush_is_bounded_when_tasks_keep_arriving():
    """A page that keeps firing requests must not hold _flush forever.

    Each drained task queues another, so the supply never runs out. The round cap is
    what makes this return; without it _flush would chase the tail indefinitely.
    """
    session = make_session()
    spawning = True

    async def refill():
        if spawning:
            session._pending.append(asyncio.create_task(refill()))

    session._pending.append(asyncio.create_task(refill()))

    # the assertion is that this returns at all
    await asyncio.wait_for(session._flush(rounds=3), timeout=5)

    # it stopped on the round cap, leaving work behind rather than looping forever
    assert session._pending

    spawning = False
    for task in session._pending:
        task.cancel()
    await asyncio.gather(*session._pending, return_exceptions=True)


async def test_flush_survives_a_task_that_raised():
    session = make_session()

    async def boom():
        raise RuntimeError("body read failed")

    session._pending.append(asyncio.create_task(boom()))
    await session._flush()  # return_exceptions=True means this must not propagate
    assert session._pending == []
