"""The client facade."""

from . import cookies as cookie_utils
from .browser import BrowserSession
from .errors import NotLoggedIn
from .models import Video
from .resources import (
    HashtagResource,
    SearchResource,
    SoundResource,
    UserResource,
    VideoResource,
)


class TikTokWeb:
    """Entry point.

        async with TikTokWeb.launch() as tt:
            async for video in tt.user("therock").videos(limit=20):
                print(video.id, video.stats.plays)

    The first launch opens a browser so you can log in; the session is cached in
    cookies.json and reused after that. TikTok serves logged-out sessions empty data,
    so a login is not optional.
    """

    def __init__(self, cookies=cookie_utils.DEFAULT_STORE, *, headless=True, chrome=None,
                 proxy=None, settle_timeout=120, body_timeout=15, login=True,
                 force_login=False, login_timeout=900, verbose=True):
        self._cookie_source = cookies
        self._headless = headless
        self._chrome = chrome
        self._proxy = proxy
        self._settle_timeout = settle_timeout
        self._body_timeout = body_timeout
        self._login = login
        self._force_login = force_login
        self._login_timeout = login_timeout
        self._verbose = verbose
        self.session = None
        self.jar = None

    # `TikTokWeb.launch(...)` reads better at a call site than `TikTokWeb(...)`
    launch = classmethod(lambda cls, *a, **kw: cls(*a, **kw))

    def log(self, message):
        if self._verbose:
            print(message, flush=True)

    async def __aenter__(self):
        self.jar = await cookie_utils.ensure(
            self._cookie_source, chrome=self._chrome, timeout=self._login_timeout,
            allow_login=self._login, force_login=self._force_login, proxy=self._proxy,
            on_message=self.log)

        if not cookie_utils.is_logged_in(self.jar):
            if self._login:
                raise NotLoggedIn("no session captured - the login did not complete")
            self.log("warning: no sessionid; TikTok will answer with empty payloads")

        self.session = await BrowserSession(
            self.jar, chrome=self._chrome, headless=self._headless, proxy=self._proxy,
            settle_timeout=self._settle_timeout, body_timeout=self._body_timeout,
            on_message=self.log).start()
        return self

    async def __aexit__(self, *exc):
        if self.session is not None:
            await self.session.close()
            self.session = None

    # ------------------------------------------------------------------ resources

    def user(self, username) -> UserResource:
        return UserResource(self, username)

    def video(self, url_or_id, username=None) -> VideoResource:
        return VideoResource(self, url_or_id, username)

    def hashtag(self, name) -> HashtagResource:
        return HashtagResource(self, name)

    def sound(self, sound_id, slug="sound") -> SoundResource:
        return SoundResource(self, sound_id, slug)

    @property
    def search(self) -> SearchResource:
        return SearchResource(self)

    async def trending(self, limit=30):
        """Yield videos from the For You feed."""
        items = await self.session.harvest("https://www.tiktok.com/foryou",
                                           "/api/recommend/item_list", limit)
        for item in items:
            yield Video.from_raw(item)

    def __repr__(self):
        state = "open" if self.session else "closed"
        return f"TikTokWeb({state}, headless={self._headless})"
