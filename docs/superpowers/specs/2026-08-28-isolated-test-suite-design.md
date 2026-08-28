# Isolated test suite for tiktokweb

**Date:** 2026-08-28
**Status:** approved, ready for implementation plan

## Problem

The repo has no test suite. The two modules that look like tests —
`tiktokweb/livetest.py` and `tiktokweb/stealthtest.py` — both ship inside the
package and both need a real browser; `livetest` additionally needs a logged-in
`cookies.json` and talks to live TikTok. There is no way to check that a parsing
change is correct without spending a browser run against a rate-limited account.

Consequence: every regression in `models.py`, `cookies.py`, `resources.py` and
`browser.py` is currently indistinguishable from TikTok's documented run-to-run
flakiness.

## Goal

A `test/` directory, isolated from the package, holding:

1. an **offline** suite that never opens a browser or touches the network, and
2. **thin wrappers** around the existing live modules, deselected by default.

`python -m tiktokweb selftest` must keep working exactly as documented.

## Non-goals

- Packaging (`setup.py`/`pyproject.toml`) or CI configuration.
- Moving `livetest.py` / `stealthtest.py` out of the package.
- Rewriting or extending what the live tests already cover.
- Mocking playwright itself. Browser-level tests use hand-written fakes only.

## Layout

```
pytest.ini                      # pythonpath = ., asyncio_mode = auto,
                                # addopts = -m "not live", markers = live
requirements-dev.txt            # pytest, pytest-asyncio
test/
  conftest.py                   # fixture loaders + FakeSession
  capture_fixtures.py           # regenerates fixtures/ from one live run
  fixtures/
    README.md                   # provenance + recapture command
    video_item.json             # one item from /api/post/item_list
    user_detail.json            # the webapp.user-detail scope
    video_detail.json           # the webapp.video-detail scope
    comment_list.json           # a /api/comment/list body
    search_user.json            # a /api/search/user body
    search_general.json         # a /api/search/general body
  unit/
    conftest.py                 # autouse no-network / no-browser guard
    test_models.py
    test_cookies.py
    test_resource_urls.py
    test_resource_wiring.py
    test_browser_capture.py
    test_cli.py
  live/
    conftest.py                 # session-scoped live run + browser fixture
    test_endpoints.py
    test_stealth.py
```

`pythonpath = .` in `pytest.ini` puts the repo root on `sys.path`, so
`import tiktokweb` resolves without a root-level `conftest.py`. `test/` is the
only new directory; `pytest.ini` and `requirements-dev.txt` are the only new
root-level files. `test/` and its subdirectories carry no `__init__.py`.

## Isolation

"Isolated" is enforced, not merely a directory name:

- **No network, no browser.** `test/unit/conftest.py` holds an autouse fixture
  that patches `socket.socket` and `playwright.async_api.async_playwright` to
  raise. A unit test that reaches out fails loudly rather than silently going
  live and passing.
- **No writes to the real cookie jar.** Cookie tests operate under `tmp_path`,
  so `cookies.save()` cannot overwrite the repo-root `cookies.json`.
- **Live tests opt-in.** Every test under `test/live/` carries
  `@pytest.mark.live`, and `addopts = -m "not live"` deselects them. Bare
  `pytest` runs only the offline suite; `pytest -m live` runs the browser suite.

## Fixtures

`test/capture_fixtures.py` is a script, not a test. It performs one live run and
writes the six response bodies verbatim, minus a recursive scrub dropping any
key matching `token|session|cookie|secret|auth`. The payloads are public-content
responses and carry no session data; the scrub is a safety net against a future
TikTok field leaking into git. `fixtures/README.md` records which account and
video each fixture came from and the command to regenerate them.

Rationale for real payloads over synthetic dicts: hand-written JSON only proves
`from_raw` handles the shape the author invented. A renamed TikTok key — the
actual failure mode this codebase is exposed to — shows up only against a
captured payload.

## Offline coverage

**test_models.py** — the six `from_raw()` classmethods against real payloads;
`statsV2` taking precedence over `stats`; `challenges` preferred over
`textExtra` for hashtags, with the fallback exercised; `_int` and `_timestamp`
returning `None` on junk input; `to_dict(raw=False)` dropping `.raw` while
`raw=True` keeps it; `missing_fields` walking nested dataclasses.

**test_cookies.py** — `load()` across all accepted forms: a file path, a json
string, a `name=value; ...` header, a cookie-manager list export, and a single
exported record; `save()` writing mode 0600; `is_logged_in`; `to_playwright`
setting `.tiktok.com`.

**test_resource_urls.py** — `VideoResource` given a full url, a share link
(`id is None`), and an id plus username; the `ValueError` when an id arrives
without a username; `@` and `#` stripping; the sound `slug-id` url.

**test_resource_wiring.py** — a `FakeSession` implementing `inline_data(url)`
and `harvest(url, path, limit, item_key=, id_key=, prepare=)`, recording its
arguments and returning fixture items. Every resource method — and
`TikTokWeb.trending()`, which lives on the client rather than a resource —
reaches the browser through exactly those two calls, so this pins:

- each endpoint path (`/api/post/item_list`, `/api/challenge/item_list`,
  `/api/music/item_list`, `/api/related/item_list`, `/api/search/user`,
  `/api/search/general`, `/api/comment/list`, `/api/recommend/item_list`)
- the `webapp.user-detail -> userInfo` and
  `webapp.video-detail -> itemInfo -> itemStruct` scope keys
- search's `item_key="user_list"` with `id_key=None`
- general search's `item.get("item") or item` unwrap

**test_browser_capture.py** — a fake response exposing `.url` and an awaitable
`.json()`; no playwright involved. Covers `_on_response` matching only
registered paths; `_drain` deduping on `id_key`, falling back to a sorted-json
key when `id_key` is `None`, setting `exhausted` on `hasMore: false`, and
swallowing a body that exceeds `body_timeout` instead of hanging; and `_flush`
retaining tasks appended *during* its await — a fake task that appends another
on completion must still be drained.

These last two are regression tests for bugs CLAUDE.md records as having already
cost this repo debugging time: the `_flush` list-swap ("silently loses captured
items and looks like an empty endpoint") and `_drain`'s unbounded body read
("deadlocked a whole test run for 39 minutes"). Both masquerade as TikTok
flakiness, which is why they earn tests before anything else in `browser.py`.

**test_cli.py** — `build_parser()` defaults, and that `selftest` is still
dispatched with its argv passed through untouched.

## Live wrappers

`test/live/conftest.py` holds a session-scoped fixture that runs
`livetest.main(["--json", <tmp>])` **once** and returns the parsed results.
Parametrized tests in `test_endpoints.py` then assert each endpoint's
`status == "PASS"`. Invoking `--only <name>` per endpoint instead would repeat
the expensive seed discovery nine times; one run gives the same per-endpoint
granularity. `livetest` keeps ownership of retries, per-case timeouts and
fresh-browser-per-endpoint.

`test_stealth.py` parametrizes `stealthtest.CASES` — already a plain list of
async functions taking a `browser` — over a session-scoped browser fixture.

Both files import from `tiktokweb`. That single reach into the package is the
deliberate cost of leaving the live modules where the CLI can find them.

## Commands

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest              # offline suite, seconds, no browser
.venv/bin/python -m pytest -m live      # browser suite
.venv/bin/python test/capture_fixtures.py
python -m tiktokweb selftest            # unchanged
```

A Testing section covering these is added to CLAUDE.md.

## Risks

- **Fixture capture needs a live run** with the repo's `cookies.json`, which per
  CLAUDE.md puts rate-limiting or ban exposure on that account. Accepted; it is
  a one-time cost, and `capture_fixtures.py` makes it repeatable rather than
  ad hoc.
- **Captured fixtures go stale.** A fixture that stops matching what TikTok
  sends makes the suite pass while production breaks. Mitigated by
  `fixtures/README.md` recording provenance and the recapture command; the live
  suite remains the check against reality.
- **`pytest-asyncio` is a second dev dependency.** Kept out of
  `requirements.txt` so the package's runtime dependency stays `playwright`
  alone.
