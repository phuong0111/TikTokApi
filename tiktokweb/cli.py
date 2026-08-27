"""Command line front end:  python -m tiktokweb <command> [...]"""

import argparse
import asyncio
import json
import sys

from . import cookies as cookie_utils
from .client import TikTokWeb
from .errors import TikTokWebError
from .models import missing_fields, to_dict


def build_parser():
    p = argparse.ArgumentParser(prog="python -m tiktokweb",
                                description="Collect TikTok data through a real browser.")
    p.add_argument("--cookies", default=str(cookie_utils.DEFAULT_STORE),
                   help="cookie jar: json file, json string, or 'name=value; ...' header")
    p.add_argument("--login", action="store_true", help="log in again, replacing the cache")
    p.add_argument("--no-headless", dest="headless", action="store_false",
                   help="show the browser (required for comments)")
    p.add_argument("--proxy", help="proxy url, e.g. http://user:pass@host:8080")
    p.add_argument("--chrome-path", help="path to a Chrome/Chromium binary")
    p.add_argument("--limit", type=int, default=20, help="items to collect (default: 20)")
    p.add_argument("--json", dest="json_out", help="write results to this json file")
    p.add_argument("--raw", action="store_true", help="include TikTok's raw payloads")
    p.add_argument("--check", action="store_true", help="report fields that came back empty")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="just capture a session and exit")
    sub.add_parser("selftest", help="run every endpoint against live TikTok "
                                    "(takes its own flags; see `selftest --help`)")

    user = sub.add_parser("user", help="a user's profile and videos")
    user.add_argument("username")
    user.add_argument("--info-only", action="store_true", help="skip the video list")

    video = sub.add_parser("video", help="one video's metadata")
    video.add_argument("url")

    comments = sub.add_parser("comments", help="a video's comments (implies --no-headless)")
    comments.add_argument("url")

    hashtag = sub.add_parser("hashtag", help="videos under a hashtag")
    hashtag.add_argument("name")

    sound = sub.add_parser("sound", help="videos using a sound")
    sound.add_argument("sound_id")

    search = sub.add_parser("search", help="search users")
    search.add_argument("term")

    sub.add_parser("trending", help="the for-you feed")
    return p


def show_video(v, index):
    print(f"[{index:>3}] {v.id}  {v.created}  {v.media.duration or '?'}s "
          f"{v.media.width}x{v.media.height}")
    print(f"      {(v.description or '(no description)')[:88]}")
    s = v.stats
    print(f"      plays={s.plays:,} likes={s.likes:,} comments={s.comments:,}"
          if s.plays is not None else "      (no stats)")
    if v.hashtags:
        print(f"      #{' #'.join(h for h in v.hashtags if h)}")


async def collect(args):
    """Returns (label, list-of-models or single model) for the chosen command."""
    headless = args.headless and args.command != "comments"
    async with TikTokWeb.launch(args.cookies, headless=headless, chrome=args.chrome_path,
                                proxy=args.proxy, force_login=args.login,
                                verbose=not args.quiet) as tt:
        if args.command == "login":
            return "session", None

        if args.command == "user":
            profile = await tt.user(args.username).info()
            print(f"\n@{profile.username} - {profile.nickname or ''}"
                  f"{' [verified]' if profile.verified else ''}")
            print(f"  followers={profile.followers:,} following={profile.following:,} "
                  f"likes={profile.likes:,} videos={profile.videos:,}\n"
                  if profile.followers is not None else "")
            if args.info_only:
                return "profile", profile
            videos = [v async for v in tt.user(args.username).videos(limit=args.limit)]
            return "videos", (profile, videos)

        if args.command == "video":
            return "video", await tt.video(args.url).info()
        if args.command == "comments":
            return "comments", [c async for c in tt.video(args.url).comments(limit=args.limit)]
        if args.command == "hashtag":
            return "videos", (None, [v async for v in tt.hashtag(args.name).videos(limit=args.limit)])
        if args.command == "sound":
            return "videos", (None, [v async for v in tt.sound(args.sound_id).videos(limit=args.limit)])
        if args.command == "search":
            return "users", [u async for u in tt.search.users(args.term, limit=args.limit)]
        if args.command == "trending":
            return "videos", (None, [v async for v in tt.trending(limit=args.limit)])

    raise SystemExit(f"unknown command {args.command}")


async def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        kind, payload = await collect(args)
    except TikTokWebError as exc:
        print(f"\n{type(exc).__name__}: {exc}", file=sys.stderr)
        print("TikTok is flaky - retry, and try --no-headless or a --proxy if it persists.",
              file=sys.stderr)
        return 2

    if kind == "session":
        print("session ready")
        return 0

    profile, items = (payload if kind == "videos" else (None, payload))
    if kind in ("video", "profile"):
        items = [payload]

    if not items:
        print("nothing collected - TikTok returned no items this run; retry.", file=sys.stderr)
        return 1

    for index, item in enumerate(items, 1):
        if kind == "comments":
            print(f"[{index:>3}] +{item.likes or 0:<6} @{item.author.username}: {item.text[:70]}")
        elif kind == "users":
            print(f"[{index:>3}] @{item.username} - {item.nickname or ''}")
        elif kind in ("videos", "video"):
            show_video(item, index)
        else:
            print(f"[{index:>3}] {item}")

    print(f"\ndone: {len(items)} item(s)")

    if args.check:
        for item in items[:1] if kind in ("video", "profile") else items:
            gaps = list(missing_fields(item))
            if gaps:
                print(f"  empty on {getattr(item, 'id', '?')}: {', '.join(gaps)}")

    if args.json_out:
        payload = {"items": [to_dict(i, raw=args.raw) for i in items]}
        if profile is not None:
            payload["profile"] = to_dict(profile, raw=args.raw)
        with open(args.json_out, "w") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        print(f"wrote {args.json_out}")

    return 0


def run():
    # selftest has its own flag set, so hand it the remaining argv untouched
    argv = sys.argv[1:]
    if "selftest" in argv:
        from .livetest import run as run_selftest
        index = argv.index("selftest")
        run_selftest(argv[:index] + argv[index + 1:])
    raise SystemExit(asyncio.run(main()))
