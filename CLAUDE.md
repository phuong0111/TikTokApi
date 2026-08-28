# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**[tiktokweb/](tiktokweb/)** is the whole codebase — a browser-driven TikTok collector. Its only third-party dependency is `playwright`; `stealth/` is vendored in.

This repo began as a fork of `davidteather/TikTokApi`. That library was removed once `tiktokweb` replaced it: its request-signing path returns empty payloads for most endpoints (see status below), so nothing depended on it. `git log` still has it if you need to look something up. No packaging config (`setup.py`/`pyproject.toml`) or CI. `README.md` is a Vietnamese-language deep dive on the anti-detection architecture, not usage docs.

## Setup

```bash
uv venv && uv pip install --python .venv/bin/python -r requirements.txt   # playwright only
```

`python -m playwright install` is **not** needed — it drives the installed Chrome via `executable_path`, autodetected by `cookies.find_chrome()`.

There are two suites: an offline `pytest` one, and the live one that talks to TikTok.

```bash
.venv/bin/python -m tiktokweb selftest                 # all endpoints, ~10 browsers
.venv/bin/python -m tiktokweb selftest --skip-comments # faster; skips the headed one
```

## Testing

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt   # pytest, pytest-asyncio
.venv/bin/python -m pytest                  # offline suite, ~0.2s, no browser
.venv/bin/python -m pytest -m live          # the browser suite (slow, needs cookies.json)
.venv/bin/python test/capture_fixtures.py   # regenerate test/fixtures/ from a live run
```

The venv is built with `uv venv` and has no `pip`, hence `uv pip` above.

`test/unit/` never opens a browser or a socket, and that is enforced rather than assumed:
an autouse fixture in [test/unit/conftest.py](test/unit/conftest.py) patches
`socket.connect` and both modules' **already-bound** `async_playwright` to raise —
patching `playwright.async_api` would not work, since `browser.py` and `cookies.py` bind
the name at import. A test that reaches out fails loudly instead of quietly going live
and passing. `addopts = -m "not live"` in `pytest.ini` keeps bare `pytest` offline.

It parses **captured** payloads from `test/fixtures/` rather than hand-written JSON, so a
renamed TikTok key fails a test. Those fixtures go stale — see
[test/fixtures/README.md](test/fixtures/README.md) for provenance, the recapture command,
and the scrubbing rule (**never** add a bare `auth` to the pattern: it matches TikTok's
own `author` keys and silently strips every item's author block). Treat `pytest -m live`
as the check against reality.

Two tests in [test/unit/test_browser_capture.py](test/unit/test_browser_capture.py) are regressions
rather than coverage — `_flush` retaining tasks appended while it awaited, and `_drain`
bounding its body read. Both were validated by injecting the bug and watching them go
red. Both bugs present as an empty endpoint or a hang, indistinguishable from TikTok's
normal flakiness, so do not delete them as redundant.

`test/live/` wraps the existing modules rather than replacing them: one
`livetest.main()` run indexed by endpoint, plus `stealthtest.CASES` one browser at a
time. `python -m tiktokweb selftest` is unchanged and still the direct way in. Note that
`pytest_collection_modifyitems` in [test/live/conftest.py](test/live/conftest.py) is a
**global** hook even though it lives in a subdirectory — it filters by path, and without
that filter it marks the entire suite `live` and deselects everything.

## Why this drives a browser (verified 2026-08-27)

The obvious approach — sign your own requests the way `davidteather/TikTokApi` does, using `window.byted_acrawler.frontierSign` in a page — still *sends* correctly, but TikTok answers most endpoints with an **empty body**, whatever the session. Measured over 5 consecutive runs with a fully logged-in session:

| Signed request | Result |
|---|---|
| `api/user/detail/`, `api/post/item_list/` | empty |
| `api/challenge/item_list/`, `api/music/detail/` | empty |
| `api/comment/list/`, `api/related/item_list/`, search | empty |
| `api/recommend/item_list/` | empty in 4/5 runs |
| `api/user/playlist`, `api/challenge/detail/` | works |
| `api/music/item_list/`, `api/mix/*` | works |

Logging in does **not** fix the empty ones — anonymous, msToken-synced and logged-in all behave the same. Don't re-investigate this; re-syncing msTokens, switching browsers and hunting for a signing bug were all tried. Note it is endpoint-specific rather than a blanket block: `music/item_list` works while `post/item_list` does not.

**The fix for the blocked ones:** open the page a real user would open and capture the XHR responses **the page makes for itself**. Same JSON, signed by TikTok's own code. [tiktokweb/browser.py](tiktokweb/browser.py) implements this; [tiktokweb/resources.py](tiktokweb/resources.py) maps each endpoint onto it.

```python
from tiktokweb import TikTokWeb

async with TikTokWeb.launch() as tt:
    profile = await tt.user("therock").info()          # Profile
    async for video in tt.user("therock").videos(limit=50):
        print(video.id, video.stats.plays, video.hashtags)

    async for c in tt.video(url).comments(limit=40):    # needs headless=False
        print(c.text, c.likes)
```

Resources: `tt.user(name)`, `tt.video(url_or_id, username=)`, `tt.hashtag(name)`, `tt.sound(id)`, `tt.search`, `tt.trending()`. Collection methods are **async generators**; `info()` calls are awaitables. Models (`Video`, `Profile`, `Comment`, `UserResult`) are dataclasses that always keep `.raw`, so a key TikTok renames costs a typed attribute but never the data. `to_dict(model, raw=False)` and `missing_fields(model)` are exported for output and coverage checks.

CLI: `python -m tiktokweb {login,selftest,user,video,comments,hashtag,sound,search,trending}`.

Measured by [tiktokweb/livetest.py](tiktokweb/livetest.py), which uses a **fresh browser per endpoint** — sequential collections in one page compound the bot check and produce failures that aren't real:

```bash
.venv/bin/python -m tiktokweb selftest                      # all endpoints
.venv/bin/python -m tiktokweb selftest --only search_users --retries 2
.venv/bin/python -m tiktokweb selftest khaby.lame --skip-comments
```

It seeds itself (collects from the account under test, then derives a video URL, sound id and hashtag from a real post), so it needs no hardcoded ids and works against any account. Exit code is the failure count.

Full run, all nine green:

| Call | Page driven | Result | Time |
|---|---|---|---|
| `user(x).info()` | `/@user` inline data | 4 keys | 7s |
| `trending()` | `/foryou` | 5 items | 8s |
| `video(u).related()` | video page | 5 items | 12s |
| `hashtag(x).videos()` | `/tag/<name>` | 5 items | 45s |
| `search.users()` | `/search/user?q=` | 5 items | 48s |
| `sound(x).videos()` | `/music/<slug>-<id>` | 5 items | 58s |
| `user(x).videos()` | `/@user` | 5 items | 72s |
| `video(u).info()` | video page inline data | 49 keys | 90s |
| `video(u).comments()` | video page (**headed**) | 5 comments | 138s |

**Everything here is flaky run to run, and retries are mandatory, not optional.** In one full run seed discovery captured nothing on its first attempt, and `search_users` needed **all three** attempts before returning data. A single EMPTY proves nothing — the suite retries twice by default and prints the `--only` command to re-check anything that still fails.

`video_comments` is the one exception to headless operation. **Headless chrome runs the page's JS but never paints the DOM here** — which is exactly why the XHR-capture endpoints work headless while comments do not: there is no comment control to click, so `/api/comment/list` is never issued (and when forced, it answers 200 with an empty body). Confirmed by the same page rendering 0 video thumbnails headless while `user_videos` still returned data from captured XHR.

With `headless=False` it works: verified live at 25 comments on one video (text, `digg_count`, and commenter `unique_id` all present; `total: 1037`). Rendering is flaky run to run — one video produced nothing while the next produced 25 — so `video_comments` retries up to 3 times and warns when called headless.

**Results vary between runs.** `related_videos` returned an empty body in one run and 5 items in the next; `trending` flipped under the library path too. Never conclude an endpoint is dead from a single run — retry with a fresh browser.

Engine details worth knowing before editing it:

- `settle()` returns as soon as the inline-data marker appears in the **server HTML**, which is *before* React hydrates. Anything touching the interactive UI must `wait_for_selector` rather than `query_selector` — that's why `video_comments` passes a `prepare` hook that waits for `[data-e2e=comment-icon]`. Headless goes further and never renders at all, so **anything DOM-dependent needs `headless=False`**; XHR capture does not.
- `BrowserSession._flush()` swaps the pending-task list before awaiting it. A plain `gather` then `clear()` drops tasks appended while the gather was in flight, which silently loses captured items and looks like an empty endpoint.
- **`stealth_async` is load-bearing, not cosmetic.** [tiktokweb/stealth/](tiktokweb/stealth/) is vendored playwright-stealth, applied to every page before navigation. Dropping it during a refactor left pages that loaded fine while never issuing their data requests — `info()` kept working (inline HTML) while every `harvest()` returned nothing. If collection goes empty across the board, check this first.
- **Every body read must be bounded.** `response.json()` waits forever on a body that never completes — one such response deadlocked a whole test run for 39 minutes. `BrowserSession._drain` wraps it in `wait_for(body_timeout)`, `_flush` bounds each gather and caps its rounds, and the suite gives every case a hard `--case-timeout`.
- The `__UNIVERSAL_DATA_FOR_REHYDRATION__` script tag sometimes carries extra React attributes (`data-floating-ui-inert`, `aria-hidden`), so the regex matches `"[^>]*>` rather than expecting `type="application/json">` immediately.

### TikTok's bot check is transient, not a block

A challenge page (~1800 bytes, `slardar_us_waf` in the markup) is served first and usually redirects to the real page within seconds. Two consequences:

- Reading `page.content()` too early yields the challenge page, and `Page.content()` raises `"page is navigating"` mid-redirect — catch and retry rather than treating either as a block.
- It sometimes just sits there. **Re-navigating clears it**; waiting alone does not. `settle()` in the collector re-`goto`s every 20s. Measured: 3/3 headless runs succeeded, clearing on attempts 1, 3, and 5. A visible browser showed no advantage (also needed 5 attempts once), so retries matter more than headless vs headed.

## Login and cookies

`TikTokWeb.launch()` handles this itself; [tiktokweb/cookies.py](tiktokweb/cookies.py) owns the flow:

```python
from tiktokweb import cookies
jar = await cookies.ensure("cookies.json")     # loads, or logs in when there is no session
```

`cookies.login()` opens a visible Chrome on TikTok's login page, polls for the `sessionid` cookie, settles on `/foryou` so `ttwid`/`msToken` are issued for a logged-in device, then writes the jar to `cookies.json` (mode 0600, gitignored). `cookies.load` also accepts a json string or a `name=value; ...` Cookie header. **A logged-in session is required** — see the status section.

`cookies.json` is a live session, equivalent to the account password. Crawling with it puts rate limiting or bans on that account, so prefer a throwaway login. Never print a resolved cookie source; it may be a raw string containing `sessionid`.

## Gotchas

### Carried over from the library that used to live here

The original `TikTokApi` fork is gone, but two of its lessons apply to any code added here:

- **Playwright proxies are `{"server": ..., "username": ..., "password": ...}` dicts.** `requests`/`httpx` look proxies up by URL scheme, so handing either the raw dict silently connects **directly** and leaks the real IP. `tiktokweb` has no direct HTTP client at all — every request goes through the browser, which honours the configured proxy — so keep it that way rather than reaching for `requests`. `VideoResource.resolve()` follows share links in-session for exactly this reason.
- **Never mutate shared state in place.** The library poisoned `session.headers` by assigning into it, leaving `range: bytes=0-` on every later request, and mutated the caller's cookie dict so concurrent sessions clobbered each other's tokens. Copy before writing.

### Other

- `tt.search.users()` is reliable; `search.videos()` uses the general-search endpoint and is less predictable.
  It returns **mixed blocks**, not just videos: searching a username yields user cards (`card_title`,
  `user_list`, `view_more`) with no `item` key, and `SearchResource.videos()` maps every block through
  `Video.from_raw()` regardless — so those come back as `Video` objects with `id=None`. Filter on
  `.id` at the call site, or search a content term rather than a name. Found 2026-08-28 while capturing
  test fixtures; the library is unchanged.
- Never print a resolved cookie source — it may be a raw cookie string containing `sessionid`.
