# Captured fixtures

**These files are gitignored — only this README is committed.** They are real
third-party data (commenter handles and comment text, account records) and this repo is
public, so the payloads stay on the machine that captured them. A fresh clone has none;
the offline suite skips the tests that need them, with a message naming the command to
capture them. Everything that does not need a fixture still runs.

Real TikTok response data, captured once so the offline suite parses the shapes TikTok
actually sends rather than shapes we invented. Hand-written JSON would only prove
`from_raw` handles the author's guess; a renamed TikTok key — the failure this codebase
is actually exposed to — shows up only against a captured payload.

| File | What it holds |
|---|---|
| `video_items.json` | items as `harvest()` returns them from `/api/post/item_list` |
| `user_detail.json` | the `webapp.user-detail` inline scope, trimmed to that one key |
| `video_detail.json` | the `webapp.video-detail` inline scope, trimmed to that one key |
| `comment_items.json` | items from `/api/comment/list` |
| `search_user_items.json` | items from `/api/search/user` |
| `search_general_items.json` | hits from `/api/search/general`, still wrapped |

Harvest-backed endpoints are stored as **item lists**, not whole response bodies: that is
exactly the boundary `FakeSession` substitutes at. Envelope behaviour (`hasMore`,
`item_key`, dedupe) is covered separately in `test/unit/test_browser_capture.py` with
hand-written bodies.

## Provenance

**Account:** @therock — seed video `7675790744828792077`
**General-search term:** `therock` (the username)
**Captured:** 2026-08-28

`search_general_items` holds **user cards**, not videos: `card_title`, `user_list`,
`view_more`, no `item` key. That is what `/api/search/general` actually returned, and
`SearchResource.videos()` maps every block through `Video.from_raw()` regardless — so
those parse to `Video` objects with `id=None`. Callers filter on `.id`.

Getting video blocks instead was tried and abandoned: the content terms `gym` and
`dance` returned an empty body on **all 7 attempts** across three runs, while the
username query answered on the first. Deterministic coverage of the `item` unwrap lives
in `test/unit/test_resource_wiring.py` with synthetic hits, precisely because TikTok
will not serve video blocks on demand.

## Recapture

    .venv/bin/python test/capture_fixtures.py
    .venv/bin/python test/capture_fixtures.py --only search_user_items

Needs a logged-in `cookies.json`, and opens a visible window for the comments capture
(`--skip-comments` avoids that, leaving `comment_items.json` stale).

Every fixture is captured with a **fresh browser** and retried three times, for the same
reason `livetest.py` isolates its cases: sequential collections in one page compound
TikTok's bot check and produce empty results that aren't real. Expect a partial run —
`search_user_items` in particular has come back empty after all three attempts — and
re-run with `--only` for whatever is missing rather than concluding an endpoint is dead.

Capturing all six took three runs plus two targeted retries. `search_user_items` was
empty for six straight attempts before answering; `comment_items` failed all three
internal render retries on one run and succeeded on the first video of the next.

## Scrubbing

Keys matching `token|session|cookie|secret|passport|csrf|sid_guard|verifyfp` are dropped
at any depth. These are public-content responses carrying no session data; the scrub is a
safety net against a future TikTok field leaking into git.

**Do not add a bare `auth` to that pattern.** An early version had it, and it matched
TikTok's own `author` / `authorName` / `authorStats` keys — every captured item lost its
entire author block, which then read as a parsing bug rather than a scrubbing one. It was
caught only because `test_models.py` asserts against real author values.

## These go stale

A fixture that stops matching what TikTok sends makes the offline suite pass while
collection breaks in production. `pytest -m live` remains the check against reality.
