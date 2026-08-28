# Isolated Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `tiktokweb` a `test/` directory holding an offline suite that never opens a browser, plus opt-in wrappers around the two existing live modules.

**Architecture:** `test/unit/` tests pure functions and wiring against captured TikTok payloads, with an autouse fixture that makes any socket or playwright use raise. Resource methods reach the browser through exactly two calls (`inline_data`, `harvest`), so a hand-written `FakeSession` covers all of them. `test/live/` marks everything `live` and is deselected by default. Nothing moves out of `tiktokweb/`; `python -m tiktokweb selftest` is untouched.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio (`asyncio_mode = auto`), playwright 1.52.0 (live tests only).

**Spec:** `docs/superpowers/specs/2026-08-28-isolated-test-suite-design.md`

## Global Constraints

- Runtime dependency stays **playwright alone**. pytest and pytest-asyncio go in `requirements-dev.txt`, never `requirements.txt`.
- **Nothing in `tiktokweb/` is moved, renamed or deleted.** `tiktokweb/livetest.py` and `tiktokweb/stealthtest.py` stay put so `cli.py:161`'s `from .livetest import run` keeps working.
- `python -m tiktokweb selftest` and every command in CLAUDE.md must behave identically after this work.
- `test/` and its subdirectories carry **no `__init__.py`**.
- Bare `.venv/bin/python -m pytest` runs **only** the offline suite and must never open a browser or a socket.
- Cookie tests write only under `tmp_path`. The repo-root `cookies.json` is a live session and must never be written by a test.
- Interpreter is always `.venv/bin/python`.
- Commit after every task.

### Deviation from the spec, applied throughout

The spec's fixture list names response *bodies* (e.g. "a `/api/comment/list` body"). This plan stores, for the four harvest-backed endpoints, the **item list** that `harvest()` returns, because that is exactly the boundary `FakeSession` substitutes at. Envelope behaviour (`hasMore`, `item_key`, dedupe) is covered in Task 4 with hand-written bodies, so nothing is lost. The two inline endpoints are stored as real scope dicts, trimmed to the single relevant key.

---

### Task 1: Test harness skeleton and the isolation guard

**Files:**
- Create: `pytest.ini`
- Create: `requirements-dev.txt`
- Create: `test/unit/conftest.py`
- Test: `test/unit/test_isolation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an autouse, function-scoped fixture `_no_network` in `test/unit/conftest.py` applied to every test under `test/unit/`. It raises `RuntimeError` on any socket connection or any call to `async_playwright()` inside `tiktokweb.browser` or `tiktokweb.cookies`. Later tasks rely on it being automatic — they never request it by name.

- [ ] **Step 1: Create the dev requirements file**

```bash
cat > requirements-dev.txt <<'EOF'
# Offline test suite. The package's runtime dependency stays playwright alone.
pytest==8.3.4
pytest-asyncio==0.25.2
EOF
```

- [ ] **Step 2: Install them into the existing venv**

Run: `.venv/bin/python -m pip install -r requirements-dev.txt`
Expected: pytest and pytest-asyncio install successfully.

- [ ] **Step 3: Create pytest.ini**

`pythonpath = .` puts the repo root on `sys.path` so `import tiktokweb` resolves; this is why no root-level `conftest.py` is needed.

```ini
[pytest]
pythonpath = .
testpaths = test
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
addopts = -m "not live"
markers =
    live: needs a real browser and a logged-in cookies.json; deselected by default
```

- [ ] **Step 4: Write the failing test**

Create `test/unit/test_isolation.py`:

```python
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
```

- [ ] **Step 5: Run it to verify it fails**

Run: `.venv/bin/python -m pytest test/unit/test_isolation.py -v`
Expected: FAIL — four failures, each `DID NOT RAISE` or a real connection error, because no guard exists yet.

- [ ] **Step 6: Write the guard**

Create `test/unit/conftest.py`. Note both playwright patches target the **already-bound names** in `tiktokweb.browser` and `tiktokweb.cookies` — patching `playwright.async_api.async_playwright` would not affect them, because both modules did `from playwright.async_api import async_playwright` at import time.

```python
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
```

- [ ] **Step 7: Run it to verify it passes**

Run: `.venv/bin/python -m pytest test/unit/test_isolation.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 8: Verify the selftest CLI still works**

Run: `.venv/bin/python -m tiktokweb selftest --help`
Expected: livetest's own help text prints. Nothing in the package changed, so this is a baseline check.

- [ ] **Step 9: Commit**

```bash
git add pytest.ini requirements-dev.txt test/unit/conftest.py test/unit/test_isolation.py
git commit -m "test: offline harness with an enforced no-network guard"
```

---

### Task 2: Cookie handling tests

**Files:**
- Test: `test/unit/test_cookies.py`

**Interfaces:**
- Consumes: the autouse `_no_network` guard from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`cookies.load()` accepts five shapes; each is exercised. `save()` must write mode 0600 because the jar is equivalent to the account password.

Create `test/unit/test_cookies.py`:

```python
"""cookies.load accepts a lot of shapes; each one is a way a user actually pastes a session."""

import json
import stat

from tiktokweb import cookies


def test_load_from_json_file(tmp_path):
    path = tmp_path / "jar.json"
    path.write_text(json.dumps({"sessionid": "abc", "ttwid": "xyz"}))
    assert cookies.load(str(path)) == {"sessionid": "abc", "ttwid": "xyz"}


def test_load_from_json_string():
    assert cookies.load('{"sessionid": "abc"}') == {"sessionid": "abc"}


def test_load_from_cookie_header():
    header = "sessionid=abc; ttwid=xyz; msToken=q1"
    assert cookies.load(header) == {"sessionid": "abc", "ttwid": "xyz", "msToken": "q1"}


def test_load_from_cookie_manager_list_export():
    export = json.dumps([
        {"name": "sessionid", "value": "abc", "domain": ".tiktok.com"},
        {"name": "ttwid", "value": "xyz"},
        {"domain": "ignored, no name or value"},
    ])
    assert cookies.load(export) == {"sessionid": "abc", "ttwid": "xyz"}


def test_load_from_single_exported_record():
    assert cookies.load('{"name": "sessionid", "value": "abc"}') == {"sessionid": "abc"}


def test_load_coerces_non_string_scalars():
    assert cookies.load('{"sessionid": "abc", "count": 3}') == {"sessionid": "abc", "count": "3"}


def test_load_drops_nested_values():
    assert cookies.load('{"sessionid": "abc", "nested": {"a": 1}}') == {"sessionid": "abc"}


def test_load_returns_none_on_empty_input():
    assert cookies.load("") is None
    assert cookies.load(None) is None
    assert cookies.load("   ") is None


def test_save_writes_0600(tmp_path):
    path = cookies.save({"sessionid": "abc"}, tmp_path / "jar.json")
    assert json.loads(path.read_text()) == {"sessionid": "abc"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_is_logged_in_requires_sessionid():
    assert cookies.is_logged_in({"sessionid": "abc"})
    assert not cookies.is_logged_in({"ttwid": "xyz"})
    assert not cookies.is_logged_in({})
    assert not cookies.is_logged_in(None)


def test_to_playwright_puts_cookies_on_the_parent_domain():
    out = cookies.to_playwright({"sessionid": "abc"})
    assert out == [{"name": "sessionid", "value": "abc", "domain": ".tiktok.com", "path": "/"}]
```

- [ ] **Step 2: Run to verify the suite executes**

Run: `.venv/bin/python -m pytest test/unit/test_cookies.py -v`
Expected: all PASS. These describe existing behaviour, so green here is the correct outcome — the value is the regression lock, not a red-to-green cycle. If any fail, the assertion has misread `cookies.py`; fix the test, not the source.

- [ ] **Step 3: Confirm the real cookie jar was untouched**

Run: `git status --short cookies.json`
Expected: no output. Every test wrote under `tmp_path`.

- [ ] **Step 4: Commit**

```bash
git add test/unit/test_cookies.py
git commit -m "test: cover cookie loading, saving and playwright conversion"
```

---

### Task 3: Resource URL construction tests

**Files:**
- Test: `test/unit/test_resource_urls.py`

**Interfaces:**
- Consumes: the autouse `_no_network` guard from Task 1.
- Produces: nothing later tasks depend on.

Resource objects take a client as their first positional argument but touch it only via `self._client.session`, which URL construction never reaches. Passing `None` is therefore correct here, and keeps this task independent of the `FakeSession` introduced in Task 8.

- [ ] **Step 1: Write the failing test**

Create `test/unit/test_resource_urls.py`:

```python
"""URL and id parsing - the part of the resource layer that needs no session at all."""

import pytest

from tiktokweb.resources import (
    HashtagResource,
    SoundResource,
    UserResource,
    VideoResource,
)


def test_user_url_and_at_stripping():
    assert UserResource(None, "therock").url == "https://www.tiktok.com/@therock"
    assert UserResource(None, "@therock").username == "therock"


def test_hashtag_url_and_hash_stripping():
    assert HashtagResource(None, "gym").url == "https://www.tiktok.com/tag/gym"
    assert HashtagResource(None, "#gym").name == "gym"


def test_sound_url_is_slug_then_id():
    assert SoundResource(None, 12345).url == "https://www.tiktok.com/music/sound-12345"
    assert SoundResource(None, 12345, "my-song").url == "https://www.tiktok.com/music/my-song-12345"


def test_sound_id_is_coerced_to_string():
    assert SoundResource(None, 12345).id == "12345"


def test_video_from_full_url_extracts_the_id():
    video = VideoResource(None, "https://www.tiktok.com/@therock/video/7123456789012345678")
    assert video.id == "7123456789012345678"
    assert video.url == "https://www.tiktok.com/@therock/video/7123456789012345678"


def test_video_from_share_link_has_no_id_until_resolved():
    video = VideoResource(None, "https://vm.tiktok.com/ZMabcdefg/")
    assert video.id is None
    assert video.url == "https://vm.tiktok.com/ZMabcdefg/"


def test_video_from_id_and_username_builds_the_canonical_url():
    video = VideoResource(None, "7123456789012345678", username="@therock")
    assert video.id == "7123456789012345678"
    assert video.url == "https://www.tiktok.com/@therock/video/7123456789012345678"


def test_video_from_bare_id_without_username_is_an_error():
    with pytest.raises(ValueError, match="username"):
        VideoResource(None, "7123456789012345678")
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest test/unit/test_resource_urls.py -v`
Expected: all PASS against the existing implementation.

- [ ] **Step 3: Commit**

```bash
git add test/unit/test_resource_urls.py
git commit -m "test: cover resource url and video-id parsing"
```

---

### Task 4: Browser capture regression tests

**Files:**
- Test: `test/unit/test_browser_capture.py`

**Interfaces:**
- Consumes: the autouse `_no_network` guard from Task 1.
- Produces: nothing later tasks depend on.

`BrowserSession.__init__` only calls `cookie_utils.find_chrome()`, which does filesystem `exists()` checks. Constructing one without `start()` is therefore safe offline, and `_on_response`, `_drain` and `_flush` can be driven directly with fakes. No playwright involved.

The `_flush` and `_drain` tests here are regressions for two bugs CLAUDE.md records as already having cost this repo debugging time — both present as an empty endpoint or a hang, which is indistinguishable from TikTok's normal flakiness.

- [ ] **Step 1: Write the failing test**

Create `test/unit/test_browser_capture.py`:

```python
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
    """A page that keeps firing requests must not hold _flush forever."""
    session = make_session()
    rounds = []

    async def refill():
        rounds.append(1)
        session._pending.append(asyncio.create_task(refill()))

    session._pending.append(asyncio.create_task(refill()))
    await session._flush(rounds=3)

    assert len(rounds) == 3
    # it stopped on the round cap rather than draining the endless supply
    assert session._pending

    for task in session._pending:
        task.cancel()


async def test_flush_survives_a_task_that_raised():
    session = make_session()

    async def boom():
        raise RuntimeError("body read failed")

    session._pending.append(asyncio.create_task(boom()))
    await session._flush()  # return_exceptions=True means this must not propagate
    assert session._pending == []
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest test/unit/test_browser_capture.py -v`
Expected: all PASS. `test_drain_is_bounded_by_body_timeout` should complete in well under a second, not 30.

- [ ] **Step 3: Prove the two regression tests actually detect their bugs**

This is the step that verifies the tests are worth keeping. Temporarily break `tiktokweb/browser.py` and confirm each test goes red.

First, `_flush`. Replace the swap at `tiktokweb/browser.py:115` with the naive version:

```python
            # TEMPORARY - the bug this test exists to catch
            pending = list(self._pending)
            self._pending.clear()
```

Run: `.venv/bin/python -m pytest test/unit/test_browser_capture.py -k flush -v`
Expected: `test_flush_keeps_tasks_appended_while_it_was_awaiting` FAILS with `drained == ["first"]`.

Then `git checkout tiktokweb/browser.py` and break `_drain` at line 93 instead:

```python
            body = await response.json()   # TEMPORARY - unbounded
```

Run: `.venv/bin/python -m pytest test/unit/test_browser_capture.py -k body_timeout -v --timeout=10` (or just observe it hang for 30s)
Expected: the test hangs or fails rather than passing.

Finally restore: `git checkout tiktokweb/browser.py`

- [ ] **Step 4: Confirm the source is back to unmodified**

Run: `git status --short tiktokweb/browser.py`
Expected: no output.

- [ ] **Step 5: Re-run to confirm green on the real source**

Run: `.venv/bin/python -m pytest test/unit/test_browser_capture.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add test/unit/test_browser_capture.py
git commit -m "test: regression tests for _flush task retention and _drain body bound"
```

---

### Task 5: CLI parser tests

**Files:**
- Test: `test/unit/test_cli.py`

**Interfaces:**
- Consumes: the autouse `_no_network` guard from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`cli.run()` imports `livetest.run` **inside the function**, so monkeypatching the attribute on the module works.

Create `test/unit/test_cli.py`:

```python
"""The argument surface, and the one piece of dispatch logic in cli.run()."""

import sys

import pytest

from tiktokweb import cli, livetest


def parse(argv):
    return cli.build_parser().parse_args(argv)


def test_defaults():
    args = parse(["trending"])
    assert args.command == "trending"
    assert args.limit == 20
    assert args.headless is True
    assert args.raw is False
    assert args.check is False
    assert args.proxy is None


def test_no_headless_flag_clears_headless():
    assert parse(["--no-headless", "trending"]).headless is False


def test_user_subcommand_takes_a_username_and_info_only():
    args = parse(["user", "therock", "--info-only"])
    assert (args.username, args.info_only) == ("therock", True)


def test_video_subcommand_takes_a_url():
    assert parse(["video", "https://www.tiktok.com/@a/video/1"]).url == \
        "https://www.tiktok.com/@a/video/1"


def test_search_subcommand_takes_a_term():
    assert parse(["search", "gym"]).term == "gym"


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        parse([])


def test_selftest_dispatch_hands_livetest_the_remaining_argv(monkeypatch):
    """selftest has its own flag set, so cli must not parse or reorder its flags."""
    captured = {}

    def fake_run(argv=None):
        captured["argv"] = argv
        raise SystemExit(0)

    monkeypatch.setattr(livetest, "run", fake_run)
    monkeypatch.setattr(sys, "argv",
                        ["tiktokweb", "--limit", "5", "selftest", "--only", "trending"])

    with pytest.raises(SystemExit):
        cli.run()

    assert captured["argv"] == ["--limit", "5", "--only", "trending"]
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest test/unit/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add test/unit/test_cli.py
git commit -m "test: cover the cli parser and selftest argv passthrough"
```

---

### Task 6: Fixture capture

**Files:**
- Create: `test/capture_fixtures.py`
- Create: `test/conftest.py`
- Create: `test/fixtures/README.md`
- Create: `test/fixtures/*.json` (generated, committed)

**Interfaces:**
- Consumes: `tiktokweb.TikTokWeb`, `tiktokweb.models.to_dict`.
- Produces: a `fixture` fixture in `test/conftest.py` with signature `fixture(name: str) -> dict | list`, loading `test/fixtures/<name>.json`. Tasks 7 and 8 use it as `fixture("video_items")` etc. Fixture names produced: `video_items` (list of video item dicts), `user_detail` (dict keyed `webapp.user-detail`), `video_detail` (dict keyed `webapp.video-detail`), `comment_items` (list), `search_user_items` (list), `search_general_items` (list).

**This task needs a live run against TikTok using the repo's `cookies.json`.** Per CLAUDE.md that puts rate-limiting or ban exposure on that account, and the comments capture opens a visible browser window. It is a one-time cost.

- [ ] **Step 1: Write the capture script**

Create `test/capture_fixtures.py`:

```python
#!/usr/bin/env python3
"""Regenerate test/fixtures/ from one live run.

    .venv/bin/python test/capture_fixtures.py
    .venv/bin/python test/capture_fixtures.py --username khaby.lame --skip-comments

Not a test - a script. The offline suite parses what this writes, so these files are
the only thing standing between a renamed TikTok key and a green suite that lies.

Payloads are public-content responses and carry no session data, but every key matching
SECRET_KEY is dropped at any depth as a safety net against a future field leaking into
git. Comments need a rendered DOM, so that capture runs headed.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tiktokweb import TikTokWeb  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SECRET_KEY = re.compile(r"token|session|cookie|secret|auth", re.I)


def scrub(value):
    """Drop anything token-shaped, at any depth."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not SECRET_KEY.search(k)}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def write(name, payload):
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / f"{name}.json"
    path.write_text(json.dumps(scrub(payload), indent=2, ensure_ascii=False))
    size = len(payload) if isinstance(payload, list) else len(payload or {})
    print(f"  wrote {path.name}  ({size} item(s)/key(s))")
    return path


async def take(iterator, limit):
    out = []
    async for item in iterator:
        out.append(item)
        if len(out) >= limit:
            break
    return out


async def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--username", default="therock")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--cookies", default="cookies.json")
    p.add_argument("--skip-comments", action="store_true",
                   help="skip the capture that opens a visible window")
    args = p.parse_args(argv)

    captured = {}

    print(f"capturing from @{args.username} (headless)...")
    async with TikTokWeb.launch(args.cookies) as tt:
        videos = await take(tt.user(args.username).videos(limit=args.count), args.count)
        if not videos:
            print("no videos collected - TikTok answered empty; retry.", file=sys.stderr)
            return 1
        captured["video_items"] = [v.raw for v in videos]

        scope = await tt.session.inline_data(tt.user(args.username).url)
        captured["user_detail"] = {"webapp.user-detail": scope.get("webapp.user-detail")}

        video_url = videos[0].url
        scope = await tt.session.inline_data(video_url)
        captured["video_detail"] = {"webapp.video-detail": scope.get("webapp.video-detail")}

        users = await take(tt.search.users(args.username, limit=args.count), args.count)
        captured["search_user_items"] = [u.raw for u in users]

        hits = await take(tt.search.videos(args.username, limit=args.count), args.count)
        captured["search_general_items"] = [h.raw for h in hits]

    if not args.skip_comments:
        print(f"capturing comments from {video_url} (a window will open)...")
        async with TikTokWeb.launch(args.cookies, headless=False) as tt:
            comments = await take(tt.video(video_url).comments(limit=args.count), args.count)
            captured["comment_items"] = [c.raw for c in comments]

    print("\nwriting fixtures:")
    empty = []
    for name, payload in captured.items():
        if not payload or (isinstance(payload, dict) and not any(payload.values())):
            empty.append(name)
            continue
        write(name, payload)

    if empty:
        print(f"\nEMPTY, not written: {', '.join(empty)}")
        print("TikTok is flaky run to run - re-run to fill the gaps.", file=sys.stderr)
        return len(empty)

    print(f"\nseed video: {video_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: Run the capture**

Run: `.venv/bin/python test/capture_fixtures.py`
Expected: exit 0, six files written under `test/fixtures/`. Per CLAUDE.md this is flaky — **re-run on a partial result**, and use `--username khaby.lame` if one account keeps coming back empty. Record the account and seed video url it prints; Step 4 needs them.

- [ ] **Step 3: Verify no secrets landed in the fixtures**

Run: `grep -rniE "sessionid|msToken|sid_guard|passport|secret" test/fixtures/ | head`
Expected: no output. If anything appears, extend `SECRET_KEY` in the script and re-run the capture before committing.

- [ ] **Step 4: Write the fixtures README**

Replace the two bracketed values with what Step 2 actually printed.

```bash
cat > test/fixtures/README.md <<'EOF'
# Captured fixtures

Real TikTok response data, captured once so the offline suite can parse the shapes
TikTok actually sends rather than shapes we invented. Hand-written JSON would only
prove `from_raw` handles the author's guess; a renamed TikTok key — the failure this
codebase is actually exposed to — shows up only against a captured payload.

| File | What it holds |
|---|---|
| `video_items.json` | items as `harvest()` returns them from `/api/post/item_list` |
| `user_detail.json` | the `webapp.user-detail` inline scope, trimmed to that one key |
| `video_detail.json` | the `webapp.video-detail` inline scope, trimmed to that one key |
| `comment_items.json` | items from `/api/comment/list` |
| `search_user_items.json` | items from `/api/search/user` |
| `search_general_items.json` | hits from `/api/search/general`, still wrapped |

Harvest-backed endpoints are stored as **item lists**, not whole response bodies:
that is exactly the boundary `FakeSession` substitutes at. Envelope behaviour
(`hasMore`, `item_key`, dedupe) is covered separately in
`test/unit/test_browser_capture.py` with hand-written bodies.

Every key matching `token|session|cookie|secret|auth` is dropped at any depth on
capture. These are public-content responses and carry no session data; the scrub is a
safety net against a future TikTok field leaking into git.

**Captured from:** @[ACCOUNT] — seed video [VIDEO_URL]
**Captured on:** 2026-08-28

## Recapture

    .venv/bin/python test/capture_fixtures.py

Needs a logged-in `cookies.json`, and opens a visible window for the comments capture
(`--skip-comments` avoids that, leaving `comment_items.json` stale). TikTok is flaky
run to run — a partial result means re-run, not that an endpoint is dead.

These go stale. A fixture that stops matching what TikTok sends makes the offline suite
pass while collection breaks in production; `pytest -m live` remains the check against
reality.
EOF
```

- [ ] **Step 5: Write the shared fixture loader**

Create `test/conftest.py`:

```python
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
```

- [ ] **Step 6: Verify the loader works and the guard still holds**

Run: `.venv/bin/python -m pytest test/unit -v`
Expected: every test from Tasks 1-5 still PASSes. `test/conftest.py` adding a session-scoped fixture must not disturb them.

- [ ] **Step 7: Commit**

```bash
git add test/capture_fixtures.py test/conftest.py test/fixtures/
git commit -m "test: capture script and real TikTok fixtures"
```

---

### Task 7: Model parsing tests

**Files:**
- Test: `test/unit/test_models.py`

**Interfaces:**
- Consumes: `fixture(name)` from Task 6's `test/conftest.py`; the autouse `_no_network` guard from Task 1.
- Produces: nothing later tasks depend on.

Assertions compare parsed attributes **against the fixture's own values**, never against hardcoded literals — that keeps the tests valid after a recapture. Precedence and coercion tests use minimal hand-written dicts, because they need two conflicting values present at once, which a real payload cannot provide.

- [ ] **Step 1: Write the failing test**

Create `test/unit/test_models.py`:

```python
"""Parsing, against real captured payloads.

Assertions read expected values out of the fixture rather than hardcoding them, so a
recapture does not invalidate the suite. The precedence cases below are hand-written
because they need two conflicting keys present at once.
"""

from datetime import datetime

from tiktokweb.models import (
    Author,
    Comment,
    Profile,
    Sound,
    Stats,
    UserResult,
    Video,
    missing_fields,
    to_dict,
)
from tiktokweb.models import _int, _timestamp


# ------------------------------------------------------------------- real payloads

def test_video_from_a_captured_item(fixture):
    item = fixture("video_items")[0]
    video = Video.from_raw(item)

    assert video.id == item["id"]
    assert video.description == (item.get("desc") or "")
    assert video.author.username == item["author"]["uniqueId"]
    assert video.url == f"https://www.tiktok.com/@{video.author.username}/video/{video.id}"
    assert video.raw is item
    assert isinstance(video.created, datetime)


def test_video_stats_come_through_as_ints(fixture):
    item = fixture("video_items")[0]
    stats = Video.from_raw(item).stats

    assert isinstance(stats.plays, int)
    assert isinstance(stats.likes, int)
    source = item.get("statsV2") or item.get("stats")
    assert stats.plays == int(source["playCount"])
    assert stats.likes == int(source["diggCount"])


def test_video_media_and_sound_are_populated(fixture):
    item = fixture("video_items")[0]
    video = Video.from_raw(item)

    assert video.media.duration == item["video"]["duration"]
    assert video.media.cover == item["video"]["cover"]
    assert video.sound.id == item["music"]["id"]


def test_every_captured_video_parses(fixture):
    for item in fixture("video_items"):
        video = Video.from_raw(item)
        assert video.id
        assert video.author.username


def test_profile_from_the_captured_user_detail_scope(fixture):
    user_info = fixture("user_detail")["webapp.user-detail"]["userInfo"]
    profile = Profile.from_raw(user_info)

    assert profile.username == user_info["user"]["uniqueId"]
    assert profile.sec_uid == user_info["user"]["secUid"]
    assert isinstance(profile.followers, int)
    assert profile.followers == int(user_info["stats"]["followerCount"])
    assert profile.raw is user_info


def test_video_from_the_captured_video_detail_scope(fixture):
    item = fixture("video_detail")["webapp.video-detail"]["itemInfo"]["itemStruct"]
    video = Video.from_raw(item)

    assert video.id == item["id"]
    assert video.author.username == item["author"]["uniqueId"]


def test_comment_from_a_captured_item(fixture):
    item = fixture("comment_items")[0]
    comment = Comment.from_raw(item)

    assert comment.id == item["cid"]
    assert comment.text == item["text"]
    assert comment.likes == int(item["digg_count"])
    assert comment.author.username == item["user"]["unique_id"]


def test_user_result_from_a_captured_search_hit(fixture):
    item = fixture("search_user_items")[0]
    result = UserResult.from_raw(item)

    info = item.get("user_info") or item.get("user") or item
    assert result.username == (info.get("uniqueId") or info.get("unique_id"))
    assert result.raw is item


def test_general_search_hits_unwrap_to_a_video(fixture):
    """General search wraps each hit; resources.py unwraps with item.get("item") or item."""
    for hit in fixture("search_general_items"):
        video = Video.from_raw(hit.get("item") or hit)
        assert video.id


# ---------------------------------------------------------------------- precedence

def test_statsv2_wins_over_stats():
    """statsV2 carries the same counters as strings and is the fresher of the two."""
    stats = Stats.from_raw({"stats": {"playCount": 1}, "statsV2": {"playCount": "999"}})
    assert stats.plays == 999


def test_stats_is_used_when_statsv2_is_absent():
    assert Stats.from_raw({"stats": {"playCount": 7}}).plays == 7


def test_stats_of_an_item_with_neither_key_is_all_none():
    assert Stats.from_raw({}) == Stats()


def test_challenges_win_over_text_extra_for_hashtags():
    video = Video.from_raw({
        "id": "1",
        "challenges": [{"title": "gym"}, {"title": "fitness"}],
        "textExtra": [{"hashtagName": "ignored"}],
    })
    assert video.hashtags == ["gym", "fitness"]


def test_text_extra_is_the_hashtag_fallback():
    video = Video.from_raw({"id": "1", "textExtra": [{"hashtagName": "gym"}]})
    assert video.hashtags == ["gym"]


def test_mentions_come_from_text_extra():
    video = Video.from_raw({
        "id": "1",
        "textExtra": [{"userUniqueId": "therock"}, {"hashtagName": "gym"}],
    })
    assert video.mentions == ["therock"]


def test_author_accepts_both_key_styles():
    assert Author.from_raw({"uniqueId": "a", "secUid": "s"}).username == "a"
    assert Author.from_raw({"unique_id": "a", "sec_uid": "s"}).username == "a"
    assert Author.from_raw({"unique_id": "a", "sec_uid": "s"}).sec_uid == "s"


def test_author_of_a_non_dict_is_empty_rather_than_an_error():
    assert Author.from_raw(None) == Author()
    assert Author.from_raw("nonsense") == Author()


def test_sound_of_an_item_without_music_is_empty():
    assert Sound.from_raw({}) == Sound()


# ------------------------------------------------------------------------ coercion

def test_int_coerces_and_gives_up_quietly():
    assert _int("42") == 42
    assert _int(42) == 42
    assert _int(None) is None
    assert _int("nonsense") is None
    assert _int({}) is None


def test_timestamp_coerces_and_gives_up_quietly():
    assert _timestamp(1600000000) == datetime.fromtimestamp(1600000000)
    assert _timestamp("1600000000") == datetime.fromtimestamp(1600000000)
    assert _timestamp(None) is None
    assert _timestamp("nonsense") is None


# ------------------------------------------------------------------ to_dict/missing

def test_to_dict_drops_raw_by_default(fixture):
    out = to_dict(Video.from_raw(fixture("video_items")[0]))
    assert "raw" not in out
    assert "raw" not in out["author"]


def test_to_dict_keeps_raw_when_asked(fixture):
    item = fixture("video_items")[0]
    out = to_dict(Video.from_raw(item), raw=True)
    assert out["raw"]["id"] == item["id"]


def test_to_dict_renders_datetimes_as_isoformat(fixture):
    out = to_dict(Video.from_raw(fixture("video_items")[0]))
    assert out["created"] == datetime.fromisoformat(out["created"]).isoformat()


def test_missing_fields_reports_empty_paths_including_nested_ones():
    video = Video(id="1", description="", hashtags=[],
                  author=Author(username="a"), stats=Stats(plays=5))
    gaps = set(missing_fields(video))

    assert "description" in gaps
    assert "hashtags" in gaps
    assert "author.nickname" in gaps
    assert "stats.likes" in gaps
    assert "id" not in gaps
    assert "author.username" not in gaps
    assert "stats.plays" not in gaps
    assert not any(g.startswith("raw") for g in gaps)
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest test/unit/test_models.py -v`
Expected: all PASS. A failure in a `fixture(...)`-backed test means either a fixture captured empty (recapture) or the fixture genuinely does not contain that key — read the fixture before changing an assertion.

- [ ] **Step 3: Commit**

```bash
git add test/unit/test_models.py
git commit -m "test: parse captured payloads through every model"
```

---

### Task 8: Resource wiring tests

**Files:**
- Modify: `test/conftest.py` (append `FakeSession` and a `fake_client` fixture)
- Test: `test/unit/test_resource_wiring.py`

**Interfaces:**
- Consumes: `fixture(name)` from Task 6.
- Produces: `FakeSession` in `test/conftest.py` with `inline_data(url)`, `harvest(url, path, limit, *, item_key="itemList", id_key="id", scroll=True, idle_limit=4, prepare=None)`, `settle(url)`, `log(message)`, attributes `.headless`, `.page`, and `.calls` — a list of tuples, harvest recorded as `("harvest", url, path, limit, item_key, id_key)` and inline as `("inline_data", url)`.

Resources reach the browser through exactly `inline_data` and `harvest`, so substituting the session covers every collection method. The client is the **real** `TikTokWeb` with `.session` assigned — constructing it runs no browser, and this way the test covers real client wiring too.

- [ ] **Step 1: Append the fake to test/conftest.py**

```python


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
```

- [ ] **Step 2: Write the failing test**

Create `test/unit/test_resource_wiring.py`:

```python
"""What each resource asks the session for.

Endpoint paths, scope keys and item_key/id_key are the things that break silently when
TikTok moves something: collection returns nothing and looks like ordinary flakiness.
"""

import pytest

from tiktokweb.models import Comment, Profile, UserResult, Video

VIDEO_URL = "https://www.tiktok.com/@therock/video/7123456789012345678"


async def drain(iterator):
    return [item async for item in iterator]


# --------------------------------------------------------------------------- inline

async def test_user_info_reads_the_user_detail_scope(fake_client, fixture):
    client, session = fake_client(inline=fixture("user_detail"))

    profile = await client.user("therock").info()

    assert isinstance(profile, Profile)
    assert profile.username
    assert session.calls == [("inline_data", "https://www.tiktok.com/@therock")]


async def test_user_info_survives_a_missing_scope_key(fake_client):
    client, _ = fake_client(inline={})
    profile = await client.user("therock").info()
    assert profile == Profile(raw={})


async def test_video_info_reads_the_video_detail_scope(fake_client, fixture):
    client, session = fake_client(inline=fixture("video_detail"))

    video = await client.video(VIDEO_URL).info()

    assert isinstance(video, Video)
    assert video.id
    assert session.calls == [("inline_data", VIDEO_URL)]


async def test_sound_info_reads_the_music_detail_scope(fake_client):
    client, session = fake_client(inline={"webapp.music-detail": {"musicInfo": {"id": "1"}}})

    info = await client.sound("12345").info()

    assert info == {"musicInfo": {"id": "1"}}
    assert session.calls == [("inline_data", "https://www.tiktok.com/music/sound-12345")]


# -------------------------------------------------------------------------- harvest

async def test_user_videos_harvests_post_item_list(fake_client, fixture):
    items = fixture("video_items")
    client, session = fake_client(items=items)

    videos = await drain(client.user("therock").videos(limit=3))

    assert all(isinstance(v, Video) for v in videos)
    assert [v.id for v in videos] == [i["id"] for i in items[:3]]
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/@therock", "/api/post/item_list", 3,
        "itemList", "id")


async def test_hashtag_videos_harvest_challenge_item_list(fake_client, fixture):
    client, session = fake_client(items=fixture("video_items"))

    await drain(client.hashtag("#gym").videos(limit=5))

    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/tag/gym", "/api/challenge/item_list", 5,
        "itemList", "id")


async def test_sound_videos_harvest_music_item_list(fake_client, fixture):
    client, session = fake_client(items=fixture("video_items"))

    await drain(client.sound("12345").videos(limit=5))

    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/music/sound-12345", "/api/music/item_list", 5,
        "itemList", "id")


async def test_related_videos_harvest_related_item_list(fake_client, fixture):
    client, session = fake_client(items=fixture("video_items"))

    await drain(client.video(VIDEO_URL).related(limit=4))

    assert session.harvest_call() == (
        "harvest", VIDEO_URL, "/api/related/item_list", 4, "itemList", "id")


async def test_trending_harvests_recommend_item_list_from_foryou(fake_client, fixture):
    """trending lives on the client rather than on a resource."""
    client, session = fake_client(items=fixture("video_items"))

    videos = await drain(client.trending(limit=5))

    assert all(isinstance(v, Video) for v in videos)
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/foryou", "/api/recommend/item_list", 5,
        "itemList", "id")


# --------------------------------------------------------------------------- search

async def test_search_users_uses_user_list_with_no_id_key(fake_client, fixture):
    """Search hits carry no stable id, hence id_key=None."""
    client, session = fake_client(items=fixture("search_user_items"))

    results = await drain(client.search.users("therock", limit=5))

    assert all(isinstance(r, UserResult) for r in results)
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/search/user?q=therock", "/api/search/user", 5,
        "user_list", None)


async def test_search_videos_uses_the_general_endpoint(fake_client, fixture):
    client, session = fake_client(items=fixture("search_general_items"))

    videos = await drain(client.search.videos("gym", limit=5))

    assert all(isinstance(v, Video) for v in videos)
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/search?q=gym", "/api/search/general", 5,
        "data", None)


async def test_search_videos_unwraps_the_general_search_wrapper(fake_client):
    """General search nests the video under "item"; a bare hit must still parse."""
    client, _ = fake_client(items=[
        {"type": 1, "item": {"id": "wrapped", "author": {"uniqueId": "a"}}},
        {"id": "bare", "author": {"uniqueId": "b"}},
    ])

    videos = await drain(client.search.videos("gym", limit=5))

    assert [v.id for v in videos] == ["wrapped", "bare"]


# ------------------------------------------------------------------------- comments

async def test_comments_harvest_comment_list_keyed_on_cid(fake_client, fixture):
    client, session = fake_client(items=fixture("comment_items"), headless=False)

    comments = await drain(client.video(VIDEO_URL).comments(limit=5))

    assert all(isinstance(c, Comment) for c in comments)
    assert session.harvest_call() == (
        "harvest", VIDEO_URL, "/api/comment/list", 5, "comments", "cid")


async def test_comments_warn_when_the_session_is_headless(fake_client, fixture):
    """Headless chrome never paints, so the comment control never exists."""
    client, session = fake_client(items=fixture("comment_items"), headless=True)

    await drain(client.video(VIDEO_URL).comments(limit=5))

    assert any(call[0] == "log" and "headless" in call[1] for call in session.calls)


async def test_comments_retry_while_nothing_comes_back(fake_client):
    """Rendering is flaky run to run, so an empty result is retried, not accepted."""
    client, session = fake_client(items=[], headless=False)

    comments = await drain(client.video(VIDEO_URL).comments(limit=5, attempts=3))

    assert comments == []
    assert len([c for c in session.calls if c[0] == "harvest"]) == 3


# --------------------------------------------------------------------------- limits

async def test_limit_is_passed_through_and_honoured(fake_client, fixture):
    items = fixture("video_items")
    client, session = fake_client(items=items)

    videos = await drain(client.user("therock").videos(limit=2))

    assert len(videos) == 2
    assert session.harvest_call()[3] == 2
```

- [ ] **Step 3: Run it**

Run: `.venv/bin/python -m pytest test/unit/test_resource_wiring.py -v`
Expected: all PASS. If `test_comments_retry_while_nothing_comes_back` fails on the count, check `VideoResource.comments`'s `attempts` default is still 3.

- [ ] **Step 4: Run the whole offline suite and time it**

Run: `time .venv/bin/python -m pytest test/unit -q`
Expected: all PASS, in seconds, with no browser window and no network access.

- [ ] **Step 5: Commit**

```bash
git add test/conftest.py test/unit/test_resource_wiring.py
git commit -m "test: pin every resource's endpoint path and capture keys"
```

---

### Task 9: Live test wrappers

**Files:**
- Create: `test/live/conftest.py`
- Create: `test/live/test_endpoints.py`
- Create: `test/live/test_stealth.py`

**Interfaces:**
- Consumes: `tiktokweb.livetest.main`, `tiktokweb.stealthtest.CASES`, `tiktokweb.cookies.find_chrome`.
- Produces: a session-scoped `live_results` fixture returning `{endpoint_name: result_row}` parsed from livetest's `--json` output.

The fixtures here are **synchronous** and call `asyncio.run` themselves. A session-scoped async fixture would need `loop_scope="session"` and drag every live test onto one event loop; livetest already owns its own loop, retries, per-case timeouts and fresh-browser-per-endpoint, so wrapping it synchronously keeps that ownership intact.

`livetest.main` is run **once** with no `--only`: invoking it per endpoint would repeat the expensive seed discovery nine times for the same granularity.

- [ ] **Step 1: Write the live conftest**

Create `test/live/conftest.py`:

```python
"""The browser-backed suite. Deselected by default; run with `pytest -m live`.

These need a logged-in cookies.json and talk to live TikTok, so they are slow, flaky by
nature, and put rate-limit exposure on the account whose session is in the jar.
"""

import asyncio
import json

import pytest

from tiktokweb import livetest


def pytest_collection_modifyitems(items):
    """Everything in this directory is live, so mark it here rather than per test."""
    for item in items:
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
```

- [ ] **Step 2: Write the endpoint tests**

Create `test/live/test_endpoints.py`:

```python
"""One test per endpoint, all reading a single live run."""

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
```

Note: `test/live/` has no `__init__.py`, so this file cannot import from `conftest` by relative path — the `live_results` fixture reaches it through pytest's fixture lookup instead, which needs no import. The endpoint names are listed inline for that reason.

- [ ] **Step 3: Write the stealth tests**

Create `test/live/test_stealth.py`:

```python
"""The vendored stealth layer, checked against about:blank - never touches TikTok.

stealth_async is load-bearing: without it pages load fine but never issue their data
requests, so info() keeps working while every harvest() returns nothing. If these fail,
collection is about to go quietly empty across the board.
"""

import asyncio

import pytest
from playwright.async_api import async_playwright

from tiktokweb import cookies as cookie_utils
from tiktokweb import stealthtest


async def _run(case):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False, args=["--headless=new"],
        executable_path=cookie_utils.find_chrome(None))
    try:
        await case(browser)
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.parametrize("case", stealthtest.CASES, ids=lambda c: c.__name__)
def test_stealth_case(case):
    """A browser per case - they load about:blank, so this is cheap."""
    asyncio.run(_run(case))
```

- [ ] **Step 4: Verify live tests are deselected by default**

Run: `.venv/bin/python -m pytest -q`
Expected: only the `test/unit` tests run. The summary must show deselected items and **no browser window opens**.

- [ ] **Step 5: Run the stealth tests only**

Run: `.venv/bin/python -m pytest test/live/test_stealth.py -m live -v`
Expected: 3 PASS, one per `stealthtest.CASES` entry. This is the cheap half of the live suite and needs no cookies.

- [ ] **Step 6: Run the full live suite**

Run: `.venv/bin/python -m pytest test/live -m live -v`
Expected: the endpoint tests take several minutes, open a window for `video_comments`, and mostly pass. Per CLAUDE.md a single failure proves nothing — re-run before treating one as real, and report which endpoints failed rather than editing the test to accept them.

- [ ] **Step 7: Commit**

```bash
git add test/live/
git commit -m "test: opt-in wrappers around the live and stealth suites"
```

---

### Task 10: Document the suite

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything built in Tasks 1-9.
- Produces: nothing.

CLAUDE.md currently states "The test suite is live-only (it talks to TikTok), so there is no offline `pytest`". That is now false and must be corrected, not merely appended to.

- [ ] **Step 1: Fix the stale claim in the Setup section**

Replace this block in `CLAUDE.md`:

```
The test suite is live-only (it talks to TikTok), so there is no offline `pytest`:
```

with:

```
There are two suites: an offline `pytest` one, and the live one that talks to TikTok.
```

- [ ] **Step 2: Add a Testing section**

Insert after the Setup section:

````markdown
## Testing

```bash
.venv/bin/python -m pip install -r requirements-dev.txt   # pytest, pytest-asyncio
.venv/bin/python -m pytest                  # offline suite, seconds, no browser
.venv/bin/python -m pytest -m live          # the browser suite (slow, needs cookies.json)
.venv/bin/python test/capture_fixtures.py   # regenerate test/fixtures/ from a live run
```

`test/unit/` never opens a browser or a socket, and that is enforced: an autouse fixture
in `test/unit/conftest.py` patches `socket.connect` and both modules' bound
`async_playwright` to raise. A test that reaches out fails loudly instead of quietly
going live and passing. `addopts = -m "not live"` in `pytest.ini` keeps bare `pytest`
offline.

It parses **captured** TikTok payloads from `test/fixtures/` rather than hand-written
JSON, so a renamed key fails a test. Those fixtures go stale: see
`test/fixtures/README.md` for provenance and the recapture command, and treat
`pytest -m live` as the check against reality.

Two tests there are regressions rather than coverage — `_flush` retaining tasks appended
while it awaited, and `_drain` bounding its body read. Both bugs present as an empty
endpoint or a hang, which is indistinguishable from TikTok's normal flakiness, so do not
delete them as redundant.

`test/live/` wraps the existing modules rather than replacing them: one `livetest.main()`
run indexed by endpoint, plus `stealthtest.CASES` one browser at a time.
`python -m tiktokweb selftest` is unchanged and still the direct way in.
````

- [ ] **Step 3: Verify every documented command works**

Run each and confirm the described behaviour:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest --collect-only -m live -q
.venv/bin/python -m tiktokweb selftest --help
.venv/bin/python -m tiktokweb --help
```
Expected: offline suite green; live tests collect but do not run; both help texts print unchanged.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the offline and live test suites"
```

---

## Verification

After Task 10, confirm the whole thing:

- [ ] `.venv/bin/python -m pytest -q` — green, seconds, no browser window, no network.
- [ ] `git status --short` — clean; in particular `cookies.json` and `tiktokweb/` are untouched by any test run.
- [ ] `git diff --stat main -- tiktokweb/` — **empty**. No file in the package was modified.
- [ ] `.venv/bin/python -m tiktokweb selftest --help` — unchanged output.
- [ ] `grep -rniE "sessionid|msToken|passport" test/fixtures/` — no output.
- [ ] `.venv/bin/python -m pytest -m live -v` — run once and report the result honestly, including which endpoints failed. Per CLAUDE.md, flakiness is expected; do not edit tests to make a flaky endpoint pass.

---

## Corrections applied during execution (2026-08-28)

The plan above is kept as written; these are the points where it was wrong and what was
done instead. Anyone re-running it should read this section first.

**Task 1 Step 2 — `pip` does not exist in this venv.** It is built with `uv venv`.
Use `uv pip install --python .venv/bin/python -r requirements-dev.txt`, matching the
setup line already in CLAUDE.md.

**Task 4 — `test_flush_is_bounded_when_tasks_keep_arriving` asserted the wrong thing.**
The plan predicted `len(rounds) == 3`; the real count was 12. `asyncio.create_task`
schedules eagerly, so a single gather round runs several refills before it settles. The
test now asserts what actually matters — that `_flush` returns at all and leaves work
behind — via `asyncio.wait_for(...)` plus a non-empty `_pending`, and stops spawning
before cleanup so it leaks no tasks.

**Task 4 Step 3 — the injected `_flush` bug was not the bug, and the test did not catch
it.** Two separate problems:

1. Clearing the pending list *before* the await is equivalent to the swap — the `rounds`
   loop still recovers the task next round. The real gather-then-clear bug clears
   *after* the await.
2. Even with the correct bug injected, the test passed: the task queued by `first()`
   completed opportunistically on the loop cycles left inside `wait_for`. It only
   detects the bug once `second()` has a genuine await point (`asyncio.sleep(0.05)`),
   which it now has.

Both regression tests were then confirmed red against the injected bug and green against
the real source. The `_drain` one stalls the full 30s when unbounded, as advertised.

**Task 6 — the scrub regex destroyed the fixtures.** `token|session|cookie|secret|auth`
matches `author`, `authorName` and `authorStats`, so every captured item lost its entire
author block. The Step 3 secret-scan passed, because nothing secret was there — nothing
checked that *legitimate* data survived. Caught by `test_models.py` asserting against
real author values. The pattern is now
`token|session|cookie|secret|passport|csrf|sid_guard|verifyfp`, and both the script and
`test/fixtures/README.md` carry a warning against re-adding a bare `auth`.

**Task 6 — one capture run is not enough, and one browser is not enough.** The plan's
script captured everything in a single session and had no retries. CLAUDE.md is explicit
that retries are mandatory and that sequential collections in one page compound the bot
check. The script now opens a **fresh browser per fixture**, retries three times, accepts
`--only` to refill just what is missing, and walks several videos for comments because
rendering is flaky per-video rather than per-run. Even so, capturing all six took three
runs plus two targeted retries: `search_user_items` was empty for six straight attempts,
and `comment_items` failed all three internal render retries on one run.

**Task 7 — `test_general_search_hits_unwrap_to_a_video` assumed the wrong payload.**
`/api/search/general` returns **mixed blocks**: a name query answers with user cards
(`card_title`, `user_list`, `view_more`, no `item` key), and `SearchResource.videos()`
maps every block through `Video.from_raw()` regardless, yielding `Video` objects with
`id=None`. Attempts to capture video blocks instead failed on all 7 tries across two
content terms. The test now asserts the real contract — parsing never raises whatever
the block type, and any hit carrying `item` unwraps correctly — with deterministic
unwrap coverage left to the synthetic case in `test_resource_wiring.py`. This behaviour
is now recorded in CLAUDE.md's Gotchas; the library itself was not changed.

**Task 9 — `pytest_collection_modifyitems` is a global hook.** Even defined in
`test/live/conftest.py`, it receives every collected item, so the plan's version marked
all 94 tests `live` and `addopts = -m "not live"` then deselected the entire suite.
It now filters on the item's path.
