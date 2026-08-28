#!/usr/bin/env python3
"""Regenerate test/fixtures/ from live TikTok.

    .venv/bin/python test/capture_fixtures.py
    .venv/bin/python test/capture_fixtures.py --only search_user_items,comment_items
    .venv/bin/python test/capture_fixtures.py --username khaby.lame --skip-comments

Not a test - a script. The offline suite parses what this writes, so these files are
the only thing standing between a renamed TikTok key and a green suite that lies.

Each fixture is captured with a **fresh browser**, and retried: sequential collections
in one page compound TikTok's bot check and produce empty results that aren't real.
That is the same reason livetest.py isolates its cases. Comments need a rendered DOM,
so that capture runs headed, and it walks several videos because rendering is flaky
per-video rather than per-run.

Payloads are public-content responses and carry no session data, but every key matching
SECRET_KEY is dropped at any depth as a safety net against a future field leaking into
git. Widening that pattern is risky in both directions: an early version included bare
"auth", which matched `author` and stripped every item's author block.

Exit code is the number of fixtures that stayed empty.
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
# Deliberately no bare "auth": it matches TikTok's own `author` / `authorName` /
# `authorStats` keys and silently strips the entire author block, which then reads as a
# parsing bug rather than a scrubbing one. Nothing credential-shaped in these payloads
# needs it - they are public-content responses.
SECRET_KEY = re.compile(
    r"token|session|cookie|secret|passport|csrf|sid_guard|verifyfp", re.I)

NAMES = ["video_items", "user_detail", "video_detail",
         "search_user_items", "search_general_items", "comment_items"]


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


def read(name):
    path = FIXTURES / f"{name}.json"
    return json.loads(path.read_text()) if path.is_file() else None


async def take(iterator, limit):
    out = []
    async for item in iterator:
        out.append(item)
        if len(out) >= limit:
            break
    return out


def filled(payload):
    if not payload:
        return False
    return any(payload.values()) if isinstance(payload, dict) else True


async def attempt(label, fn, args, *, retries, headless=True):
    """Run fn(tt) against a fresh browser, retrying while it comes back empty."""
    for index in range(1, retries + 1):
        try:
            async with TikTokWeb.launch(args.cookies, headless=headless,
                                        verbose=False) as tt:
                out = await fn(tt)
        except Exception as exc:
            print(f"  {label}: {type(exc).__name__}: {exc}")
            out = None
        if filled(out):
            return out
        if index < retries:
            print(f"  {label}: empty, retry {index}/{retries}")
    print(f"  {label}: EMPTY after {retries} attempt(s)")
    return None


async def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--username", default="therock")
    p.add_argument("--search-term",
                   help="term for the general-search fixture (default: --username). "
                        "Content terms like 'gym' or 'dance' returned an empty body on "
                        "every one of 7 attempts; the username query answers reliably, "
                        "though with user cards rather than videos")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--cookies", default="cookies.json")
    p.add_argument("--only", help=f"comma-separated fixture names ({', '.join(NAMES)})")
    p.add_argument("--retries", type=int, default=3,
                   help="attempts per fixture, each with a fresh browser (default: 3)")
    p.add_argument("--skip-comments", action="store_true",
                   help="skip the capture that opens a visible window")
    args = p.parse_args(argv)

    wanted = set(NAMES)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        unknown = wanted - set(NAMES)
        if unknown:
            print(f"unknown fixture(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
    if args.skip_comments:
        wanted.discard("comment_items")

    user_url = f"https://www.tiktok.com/@{args.username}"
    captured, empty = {}, []

    def keep(name, payload):
        if filled(payload):
            captured[name] = payload
        else:
            empty.append(name)

    # video_items seeds the video url the two video-shaped fixtures need, so it runs
    # whenever one of them is wanted, even if it is not itself being rewritten.
    needs_video = wanted & {"video_items", "video_detail", "comment_items"}
    videos = None
    if needs_video:
        print(f"video_items from @{args.username}")
        videos = await attempt(
            "video_items",
            lambda tt: take(tt.user(args.username).videos(limit=args.count), args.count),
            args, retries=args.retries)
        if "video_items" in wanted:
            keep("video_items", [v.raw for v in videos] if videos else None)

    video_urls = [v.url for v in videos] if videos else []
    if not video_urls:
        stored = read("video_items")
        if stored:
            video_urls = [f"https://www.tiktok.com/@{i['author']['uniqueId']}"
                          f"/video/{i['id']}" for i in stored]
            print(f"  (falling back to {len(video_urls)} video url(s) from the stored fixture)")

    if "user_detail" in wanted:
        print("user_detail")
        scope = await attempt("user_detail",
                              lambda tt: tt.session.inline_data(user_url),
                              args, retries=args.retries)
        keep("user_detail", {"webapp.user-detail": (scope or {}).get("webapp.user-detail")})

    if "video_detail" in wanted:
        print("video_detail")
        if not video_urls:
            keep("video_detail", None)
        else:
            scope = await attempt("video_detail",
                                  lambda tt: tt.session.inline_data(video_urls[0]),
                                  args, retries=args.retries)
            keep("video_detail",
                 {"webapp.video-detail": (scope or {}).get("webapp.video-detail")})

    if "search_user_items" in wanted:
        print("search_user_items")
        users = await attempt(
            "search_user_items",
            lambda tt: take(tt.search.users(args.username, limit=args.count), args.count),
            args, retries=args.retries)
        keep("search_user_items", [u.raw for u in users] if users else None)

    if "search_general_items" in wanted:
        print("search_general_items")
        hits = await attempt(
            "search_general_items",
            lambda tt: take(tt.search.videos(args.search_term or args.username,
                                             limit=args.count), args.count),
            args, retries=args.retries)
        keep("search_general_items", [h.raw for h in hits] if hits else None)

    if "comment_items" in wanted:
        print("comment_items (a window will open)")
        comments = None
        # rendering is flaky per video, not per run: one video yields nothing while the
        # next yields 25, so walk candidates rather than retrying the same url
        for url in video_urls[:args.count]:
            print(f"  trying {url[-19:]}")
            comments = await attempt(
                "comment_items",
                lambda tt, u=url: take(tt.video(u).comments(limit=args.count), args.count),
                args, retries=1, headless=False)
            if comments:
                break
        keep("comment_items", [c.raw for c in comments] if comments else None)

    print("\nwriting fixtures:")
    for name, payload in captured.items():
        write(name, payload)

    if empty:
        print(f"\nEMPTY, not written: {', '.join(empty)}")
        print(f"TikTok is flaky run to run - re-run with "
              f"--only {','.join(empty)}", file=sys.stderr)
    return len(empty)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
