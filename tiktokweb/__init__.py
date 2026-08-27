"""tiktokweb - collect TikTok data through a real browser.

TikTok answers most of its web API with empty payloads when you sign the requests
yourself, whatever session you use. This package instead drives the pages a real user
would visit and captures the responses the page fetches for itself.

    import asyncio
    from tiktokweb import TikTokWeb

    async def main():
        async with TikTokWeb.launch() as tt:
            profile = await tt.user("therock").info()
            print(profile.nickname, profile.followers)

            async for video in tt.user("therock").videos(limit=20):
                print(video.id, video.stats.plays, video.hashtags)

    asyncio.run(main())

Comments need a rendered DOM, so use TikTokWeb.launch(headless=False) for those.
"""

from .client import TikTokWeb
from .errors import LoginAborted, NotLoggedIn, PageBlocked, TikTokWebError
from .models import (
    Author,
    Comment,
    Media,
    Profile,
    Sound,
    Stats,
    UserResult,
    Video,
    missing_fields,
    to_dict,
)

__all__ = [
    "TikTokWeb",
    "TikTokWebError", "LoginAborted", "NotLoggedIn", "PageBlocked",
    "Video", "Profile", "Comment", "UserResult", "Author", "Stats", "Media", "Sound",
    "to_dict", "missing_fields",
]
__version__ = "0.1.0"
