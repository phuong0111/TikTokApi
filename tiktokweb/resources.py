"""Resource objects: the chainable surface hanging off a TikTokWeb client."""

import asyncio
import re

from .errors import TikTokWebError
from .models import Comment, Profile, UserResult, Video

VIDEO_ID = re.compile(r"/video/(\d+)")


class Resource:
    def __init__(self, client):
        self._client = client

    @property
    def _session(self):
        return self._client.session


class UserResource(Resource):
    """`tt.user("therock")`"""

    def __init__(self, client, username):
        super().__init__(client)
        self.username = username.lstrip("@")

    @property
    def url(self):
        return f"https://www.tiktok.com/@{self.username}"

    async def info(self) -> Profile:
        """The account header, read from the profile page's inline data."""
        scope = await self._session.inline_data(self.url)
        return Profile.from_raw(scope.get("webapp.user-detail", {}).get("userInfo", {}))

    async def videos(self, limit=30):
        """Yield the user's videos, newest first."""
        for item in await self._session.harvest(self.url, "/api/post/item_list", limit):
            yield Video.from_raw(item)

    def __repr__(self):
        return f"UserResource(@{self.username})"


class VideoResource(Resource):
    """`tt.video(url)` or `tt.video(id, username=...)`"""

    def __init__(self, client, url_or_id, username=None):
        super().__init__(client)
        text = str(url_or_id).strip()
        if text.startswith("http"):
            self.url = text
            match = VIDEO_ID.search(text)
            # a share link (vm.tiktok.com/xxxx) carries no id until it redirects
            self.id = match.group(1) if match else None
        else:
            if not username:
                raise ValueError("pass the full video url, or an id together with username=")
            self.id = text
            self.url = f"https://www.tiktok.com/@{str(username).lstrip('@')}/video/{text}"

    async def resolve(self):
        """Follow a share link to the canonical video url, in-session.

        Resolving in the browser rather than with a separate http client keeps the same
        cookies and proxy - a plain request would go out unauthenticated, and from the
        real IP if a proxy is configured.
        """
        if self.id:
            return self
        await self._session.settle(self.url)
        final = self._session.page.url
        match = VIDEO_ID.search(final)
        if not match:
            raise TikTokWebError(f"{self.url} did not resolve to a video url (got {final})")
        self.id, self.url = match.group(1), final.split("?")[0]
        self._session.log(f"resolved share link -> {self.url}")
        return self

    async def info(self) -> Video:
        await self.resolve()
        scope = await self._session.inline_data(self.url)
        item = scope.get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
        return Video.from_raw(item)

    async def comments(self, limit=20, attempts=3):
        """Yield comments.

        Requires a headed session: headless chrome runs the page's JS but never paints,
        so the comment control never exists and the request is never issued. Rendering is
        flaky run to run, hence the retries.
        """
        await self.resolve()
        if self._session.headless:
            self._session.log("comments need a rendered page - use headless=False, or expect none")

        async def open_panel():
            # settle() returns on the server HTML marker, before react hydrates
            for selector in ("[data-e2e=comment-icon]", "[data-e2e=comment-count]",
                             "[data-e2e=browse-comment]"):
                try:
                    icon = await self._session.page.wait_for_selector(
                        selector, timeout=15000, state="visible")
                except Exception:
                    continue
                if icon:
                    try:
                        await icon.click(timeout=5000)
                    except Exception:
                        pass
                    break
            await asyncio.sleep(2.5)
            # park the cursor over the comment column so the wheel scrolls it, not the page
            size = self._session.page.viewport_size or {"width": 1280, "height": 720}
            await self._session.page.mouse.move(size["width"] - 200, size["height"] // 2)

        items = []
        for attempt in range(1, attempts + 1):
            items = await self._session.harvest(
                self.url, "/api/comment/list", limit,
                item_key="comments", id_key="cid", prepare=open_panel)
            if items:
                break
            if attempt < attempts:
                self._session.log(f"no comments rendered, retrying ({attempt}/{attempts})")

        for item in items:
            yield Comment.from_raw(item)

    async def related(self, limit=16):
        await self.resolve()
        for item in await self._session.harvest(self.url, "/api/related/item_list", limit):
            yield Video.from_raw(item)

    def __repr__(self):
        return f"VideoResource({self.id})"


class HashtagResource(Resource):
    """`tt.hashtag("gym")`"""

    def __init__(self, client, name):
        super().__init__(client)
        self.name = name.lstrip("#")

    @property
    def url(self):
        return f"https://www.tiktok.com/tag/{self.name}"

    async def videos(self, limit=30):
        for item in await self._session.harvest(self.url, "/api/challenge/item_list", limit):
            yield Video.from_raw(item)

    def __repr__(self):
        return f"HashtagResource(#{self.name})"


class SoundResource(Resource):
    """`tt.sound(music_id)` - the slug is cosmetic, only the trailing id matters."""

    def __init__(self, client, sound_id, slug="sound"):
        super().__init__(client)
        self.id = str(sound_id)
        self.slug = slug

    @property
    def url(self):
        return f"https://www.tiktok.com/music/{self.slug}-{self.id}"

    async def info(self):
        scope = await self._session.inline_data(self.url)
        return scope.get("webapp.music-detail", {})

    async def videos(self, limit=30):
        for item in await self._session.harvest(self.url, "/api/music/item_list", limit):
            yield Video.from_raw(item)

    def __repr__(self):
        return f"SoundResource({self.id})"


class SearchResource(Resource):
    """`tt.search.users(...)`"""

    async def users(self, term, limit=10):
        url = f"https://www.tiktok.com/search/user?q={term}"
        items = await self._session.harvest(url, "/api/search/user", limit,
                                            item_key="user_list", id_key=None)
        for item in items:
            yield UserResult.from_raw(item)

    async def videos(self, term, limit=10):
        url = f"https://www.tiktok.com/search?q={term}"
        items = await self._session.harvest(url, "/api/search/general", limit,
                                            item_key="data", id_key=None)
        for item in items:
            # general search wraps each hit; unwrap when it does
            yield Video.from_raw(item.get("item") or item)

    def __repr__(self):
        return "SearchResource()"
