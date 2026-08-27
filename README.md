# tiktokweb

Collect TikTok data through a real browser.

TikTok answers most of its web API with **empty payloads** when you sign the requests
yourself — whatever session you use, logged in or not. So this package doesn't sign
anything. It opens the page a real user would open and captures the XHR responses
**the page fetches for itself**: the same JSON, signed by TikTok's own code.

```python
import asyncio
from tiktokweb import TikTokWeb

async def main():
    async with TikTokWeb.launch() as tt:
        profile = await tt.user("therock").info()
        print(profile.nickname, f"{profile.followers:,} followers")

        async for video in tt.user("therock").videos(limit=20):
            print(video.id, video.stats.plays, video.hashtags)

asyncio.run(main())
```

## Install

```bash
uv venv && uv pip install --python .venv/bin/python -r requirements.txt
```

`playwright` is the only dependency, and `playwright install` is **not** needed — your
installed Chrome is driven directly and autodetected. Pass `chrome=` to point at a
different binary.

## Logging in

TikTok serves logged-out sessions empty data, so a login is required. The first run opens
a visible Chrome on the login page, waits for you to sign in, and caches the cookie jar to
`cookies.json` (mode `0600`). Every later run reuses it and needs no window.

```python
async with TikTokWeb.launch() as tt:            # logs in if cookies.json has no session
    ...

async with TikTokWeb.launch(force_login=True) as tt:   # log in again
    ...
```

You can also supply cookies yourself — a JSON file, a JSON string, or a raw
`name=value; ...` Cookie header copied from DevTools:

```python
TikTokWeb.launch("cookies.json")
TikTokWeb.launch("sessionid=...; msToken=...; ttwid=...")
```

> `cookies.json` is a live session, equivalent to your password. Rate limiting and bans
> land on whichever account you log in as, so prefer a throwaway account.

## API

`info()` calls are awaitables; collection methods are **async generators**.

```python
async with TikTokWeb.launch() as tt:
    await tt.user("therock").info()                    # -> Profile
    tt.user("therock").videos(limit=50)                # -> Video
    tt.hashtag("gym").videos(limit=30)                 # -> Video
    tt.sound(music_id).videos(limit=30)                # -> Video
    await tt.sound(music_id).info()                    # -> dict
    tt.trending(limit=30)                              # -> Video
    tt.search.users("therock", limit=10)               # -> UserResult

    video = tt.video("https://www.tiktok.com/@therock/video/7675790744828792077")
    await video.info()                                 # -> Video
    video.related(limit=16)                            # -> Video
    video.comments(limit=40)                           # -> Comment  (needs headless=False)
```

Share links work too — `tt.video("https://vm.tiktok.com/ZMabc/")` resolves in-session, so
the redirect is followed with your cookies and proxy rather than leaking a bare request.
You can also pass an id with `tt.video("7675...", username="therock")`.

### Models

`Video`, `Profile`, `Comment` and `UserResult` are dataclasses, and each keeps `.raw` —
if TikTok renames a key you lose a typed attribute, never the data.

```python
video.id                 # "7675790744828792077"
video.created            # datetime
video.description
video.stats.plays        # int, parsed from statsV2's strings
video.stats.likes, .comments, .shares, .saves
video.author.username, .nickname, .verified, .sec_uid
video.media.duration, .width, .height, .cover
video.sound.title, .author, .original
video.hashtags, video.mentions
video.raw                # TikTok's untouched payload
```

Two helpers are exported: `to_dict(model, raw=False)` for JSON output, and
`missing_fields(model)` to list fields that came back empty — handy for spotting a key
TikTok has renamed.

## Command line

```bash
python -m tiktokweb user therock --limit 50 --json out.json --check
python -m tiktokweb comments "https://www.tiktok.com/@therock/video/7675..."
python -m tiktokweb hashtag gym --limit 30
python -m tiktokweb search therock
python -m tiktokweb trending --limit 20
python -m tiktokweb login
```

Common flags: `--limit`, `--json`, `--raw`, `--check`, `--no-headless`, `--proxy`,
`--cookies`, `--chrome-path`.

## Two things that will surprise you

**Headless works for everything except comments.** Headless Chrome runs the page's
JavaScript but never paints the DOM, so XHR capture works fine while anything DOM-driven
does not — the comment control never exists to be clicked. `comments()` therefore needs
`TikTokWeb.launch(headless=False)`; the CLI's `comments` command sets that for you.

**Results are flaky run to run, and retries are mandatory.** TikTok serves a bot-check
page that usually redirects to the real page within seconds but sometimes just sits there;
re-navigating clears it, waiting does not. Beyond that, a page can clear the check and
still return nothing. A single empty result proves nothing about an endpoint.

## Tests

The suite is live-only — it talks to real TikTok, one **fresh browser per endpoint**,
because sequential collections in one page compound the bot check and produce failures
that aren't real.

```bash
python -m tiktokweb selftest                  # all endpoints
python -m tiktokweb selftest --skip-comments  # faster; skips the headed one
python -m tiktokweb selftest khaby.lame       # a different account
```

It seeds itself from the account under test, so no ids are hardcoded. Exit code is the
number of failures. Last full run, 9/9 green:

| Endpoint | Result | Time |
|---|---|---|
| `user(x).videos()` | 5 items | 6.0s |
| `user(x).info()` | Profile | 45.4s |
| `hashtag(x).videos()` | 5 items | 45.8s |
| `video(u).info()` | Video | 45.6s |
| `video(u).related()` | 5 items | 8.3s |
| `trending()` | 5 items | 7.7s |
| `search.users()` | 5 items | 46.2s |
| `sound(x).videos()` | 5 items | 9.7s |
| `video(u).comments()` | 5 comments | 8.1s |

Two of those needed retries to get there, which is normal.

## Limitations

- Comments require a visible browser.
- `user.liked` is not exposed — liked videos are private by default and return nothing.
- No media downloads; this collects metadata only.
- Timings above are from one machine and one account; yours will differ.

## Credits

Started as a fork of [davidteather/TikTokApi](https://github.com/davidteather/TikTokApi).
That library's request-signing approach no longer returns data for most endpoints, so
`tiktokweb` replaced it; the vendored `stealth/` package still comes from there. Earlier
history is in `git log`.
