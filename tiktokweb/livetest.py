#!/usr/bin/env python3
"""Exercise every endpoint against live TikTok.

    python -m tiktokweb selftest                     # all endpoints, default account
    python -m tiktokweb selftest khaby.lame          # a different account
    python -m tiktokweb selftest --only user_videos,trending
    python -m tiktokweb selftest --skip-comments     # skip the one that opens a window

Each endpoint gets a **fresh browser**. Sequential collections in one page compound
TikTok's bot check and produce failures that aren't real, so isolation is the only way
to get a trustworthy result.

`video_comments` needs a rendered DOM, so it runs with headless=False and opens a visible
window; everything else is headless. Exit code is the number of failed endpoints.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from . import cookies as cookie_utils
from .client import TikTokWeb


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m tiktokweb selftest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("username", nargs="?", default="therock", help="account to test against")
    p.add_argument("--count", type=int, default=5, help="items to request per endpoint (default: 5)")
    p.add_argument("--only", help="comma-separated endpoint names to run")
    p.add_argument("--skip-comments", action="store_true", help="skip the endpoint that needs a window")
    p.add_argument("--headed", action="store_true", help="run every endpoint with a visible browser")
    p.add_argument("--cookies", default="cookies.json", help="cookie jar (default: cookies.json)")
    p.add_argument("--login-timeout", type=int, default=900)
    p.add_argument("--retries", type=int, default=2,
                   help="retry an endpoint that returns nothing (default: 2; search_users has "
                        "needed all three attempts)")
    p.add_argument("--case-timeout", type=int, default=240,
                   help="hard per-endpoint deadline in seconds (default: 240; comments gets 3x)")
    p.add_argument("--json", dest="json_out", type=Path, help="write results to this json file")
    return p.parse_args(argv)


# --------------------------------------------------------------------------- shaping

async def drain(iterator, limit=None):
    """Async iterator -> list, so a case can report a count."""
    out = []
    async for item in iterator:
        out.append(item)
        if limit and len(out) >= limit:
            break
    return out


def build_cases(args, seed):
    """seed carries a video url / sound id / hashtag discovered from the account."""
    n = args.count
    user, url, sound, tag = args.username, seed["video_url"], seed["sound_id"], seed["hashtag"]
    return [
        # name,            needs a rendered DOM, call
        ("user_videos",    False, lambda tt: drain(tt.user(user).videos(limit=n), n)),
        ("user_info",      False, lambda tt: tt.user(user).info()),
        ("hashtag_videos", False, lambda tt: drain(tt.hashtag(tag).videos(limit=n), n)),
        ("video_info",     False, lambda tt: tt.video(url).info()),
        ("related_videos", False, lambda tt: drain(tt.video(url).related(limit=n), n)),
        ("trending",       False, lambda tt: drain(tt.trending(limit=n), n)),
        ("search_users",   False, lambda tt: drain(tt.search.users(user, limit=n), n)),
        ("sound_videos",   False, lambda tt: drain(tt.sound(sound).videos(limit=n), n)),
        ("video_comments", True,  lambda tt: drain(tt.video(url).comments(limit=n), n)),
    ]


# ----------------------------------------------------------------------------- runner

async def client(args, headless=True):
    return TikTokWeb.launch(args.cookies, headless=headless, login=False, verbose=False)


async def discover_seed(jar_ok, args, attempts=3):
    """Derive a real video url, sound id and hashtag from the account under test.

    Retried: a run can clear the bot check and still capture nothing, and aborting the
    whole suite on one empty collection wastes the other eight endpoints.
    """
    videos = []
    for attempt in range(1, attempts + 1):
        async with await client(args) as tt:
            videos = await drain(tt.user(args.username).videos(limit=5), 5)
        if videos:
            break
        if attempt < attempts:
            print(f"  nothing captured (attempt {attempt}/{attempts}), retrying...", flush=True)
    if not videos:
        return None

    pick = next((v for v in videos if v.hashtags), videos[0])
    return {"video_url": pick.url, "sound_id": pick.sound.id,
            "hashtag": pick.hashtags[0] if pick.hashtags else "gym"}


def describe(result):
    """One line of evidence that the call returned something real."""
    if isinstance(result, list):
        return str(result[0]) if result else ""
    return str(result)


def size(result):
    return len(result) if isinstance(result, list) else (1 if result else 0)


async def run_case(name, needs_render, call, args, budget):
    """One endpoint, one browser, one hard deadline - a stuck page must not stall the suite."""
    started = time.monotonic()

    async def once():
        async with await client(args, headless=not (needs_render or args.headed)) as tt:
            return await call(tt)

    try:
        result = await asyncio.wait_for(once(), timeout=budget)
        elapsed = round(time.monotonic() - started, 1)
        if not size(result):
            return {"name": name, "status": "EMPTY", "n": 0, "seconds": elapsed, "sample": ""}
        return {"name": name, "status": "PASS", "n": size(result), "seconds": elapsed,
                "sample": describe(result)[:60]}
    except asyncio.TimeoutError:
        return {"name": name, "status": "TIMEOUT", "n": 0,
                "seconds": round(time.monotonic() - started, 1), "sample": f"exceeded {budget}s"}
    except Exception as exc:
        return {"name": name, "status": type(exc).__name__, "n": 0,
                "seconds": round(time.monotonic() - started, 1), "sample": str(exc)[:50]}


async def main(argv=None):
    args = parse_args(argv)
    jar = await cookie_utils.ensure(args.cookies, timeout=args.login_timeout)
    if not cookie_utils.is_logged_in(jar):
        print("no session captured - cannot test.", file=sys.stderr)
        return 1

    print(f"account @{args.username} | {args.count} items per endpoint | "
          f"{'headed' if args.headed else 'headless (comments headed)'}\n")

    print("discovering a video / sound / hashtag to test against...")
    try:
        seed = await asyncio.wait_for(discover_seed(True, args),
                                      timeout=args.case_timeout * 3)  # it retries internally
    except asyncio.TimeoutError:
        print(f"seed discovery exceeded {args.case_timeout * 3}s - TikTok is not answering; retry later.",
              file=sys.stderr)
        return 1
    if not seed:
        print("could not collect any video from that account - cannot seed the other tests.",
              file=sys.stderr)
        return 1
    print(f"  video {seed['video_url'][-19:]} | sound {seed['sound_id']} | #{seed['hashtag']}\n")

    cases = build_cases(args, seed)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        unknown = wanted - {c[0] for c in cases}
        if unknown:
            print(f"unknown endpoint(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        cases = [c for c in cases if c[0] in wanted]
    if args.skip_comments:
        cases = [c for c in cases if c[0] != "video_comments"]

    results = []
    for name, needs_render, call in cases:
        note = " (opens a window)" if needs_render and not args.headed else ""
        print(f"  {name}{note} ...", end="", flush=True)
        budget = args.case_timeout * (3 if needs_render else 1)  # comments retries internally
        row = await run_case(name, needs_render, call, args, budget)
        # retry anything that isn't a pass: EMPTY, PageBlocked and TIMEOUT are all
        # transient here, and only a repeated failure says an endpoint is really broken
        if row["status"] != "PASS" and args.retries:
            for attempt in range(1, args.retries + 1):
                print(f"\r  {name:16} {row['status'].lower()}, retry {attempt}/{args.retries} ...",
                      end="", flush=True)
                row = await run_case(name, needs_render, call, args, budget)
                if row["status"] == "PASS":
                    break
        results.append(row)
        print(f"\r  {row['name']:16} {row['status']:14} n={row['n']:<4} "
              f"{row['seconds']:>5}s  {row['sample']}")

    failed = [r for r in results if r["status"] != "PASS"]
    print(f"\n{len(results) - len(failed)}/{len(results)} endpoints returned data")
    if failed:
        print("failed: " + ", ".join(f"{r['name']}({r['status']})" for r in failed))
        print("\nTikTok is flaky run to run - a single EMPTY is not proof an endpoint is dead.")
        print("Re-run the failures with:  --only " + ",".join(r["name"] for r in failed))

    if args.json_out:
        args.json_out.write_text(json.dumps({"username": args.username, "seed": seed,
                                             "results": results}, indent=2))
        print(f"wrote {args.json_out}")

    return len(failed)


def run(argv=None):
    raise SystemExit(asyncio.run(main(argv)))


if __name__ == "__main__":
    run()
