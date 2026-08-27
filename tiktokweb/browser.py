"""The collection engine.

Signing our own API requests only works for some endpoints - TikTok answers the rest
empty however the session is authenticated. So we open the page a real user would open
and capture the XHR responses **the page makes for itself**: same JSON, signed by
TikTok's own code.

Two constraints fall out of that and shape everything here:

* Pages are served behind a bot check that usually redirects to the real page within
  seconds but sometimes just sits there. Re-navigating clears it; waiting does not.
* Headless chrome runs the page's JS but never paints the DOM, so XHR capture works
  headless while anything DOM-driven (the comment panel) needs headless=False.
"""

import asyncio
import json
import re
import time

from playwright.async_api import async_playwright

from . import cookies as cookie_utils
from .errors import PageBlocked
from .stealth import stealth_async

# React sometimes adds attributes (data-floating-ui-inert, aria-hidden) after the type,
# so match to the end of the tag rather than expecting `type="application/json">`.
UNIVERSAL_DATA = re.compile(
    r'__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S
)


class BrowserSession:
    """One browser page, reused across collections."""

    def __init__(self, jar=None, *, chrome=None, headless=True, proxy=None,
                 settle_timeout=120, body_timeout=15, on_message=None):
        self.jar = jar or {}
        self.chrome = cookie_utils.find_chrome(chrome)
        self.headless = headless
        self.proxy = {"server": proxy} if isinstance(proxy, str) else proxy
        self.settle_timeout = settle_timeout
        self.body_timeout = body_timeout
        self._on_message = on_message
        self._captures = []
        self._pending = []

    def log(self, message):
        if self._on_message:
            self._on_message(message)

    # ------------------------------------------------------------------ lifecycle

    async def start(self):
        self._pw = await async_playwright().start()
        # --headless=new via args rather than playwright's own headless flag
        self._browser = await self._pw.chromium.launch(
            headless=False, args=["--headless=new"] if self.headless else None,
            executable_path=self.chrome, proxy=self.proxy)
        self._context = await self._browser.new_context()
        if self.jar:
            await self._context.add_cookies(cookie_utils.to_playwright(self.jar))
        self.page = await self._context.new_page()
        # hides the automation tells before any tiktok script runs; without it the page
        # loads but never issues its data requests
        await stealth_async(self.page)
        self.page.on("response", self._on_response)
        return self

    async def close(self):
        await self._flush()
        await self._browser.close()
        await self._pw.stop()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc):
        await self.close()

    # ------------------------------------------------------------------ capturing

    def _on_response(self, response):
        for capture in self._captures:
            if capture["path"] in response.url:
                self._pending.append(asyncio.create_task(self._drain(response, capture)))
                return

    async def _drain(self, response, capture):
        try:
            # playwright waits indefinitely for a body that never completes
            body = await asyncio.wait_for(response.json(), timeout=self.body_timeout)
        except Exception:
            return  # aborted, timed out, or not json

        for item in body.get(capture["item_key"]) or []:
            key = item.get(capture["id_key"]) if capture["id_key"] else json.dumps(item, sort_keys=True)
            if key is not None and key not in capture["seen"]:
                capture["seen"].add(key)
                capture["items"].append(item)
        if body.get("hasMore") in (False, 0):
            capture["exhausted"] = True

    async def _flush(self, rounds=5):
        """Await in-flight body reads.

        Swap the list before awaiting: tasks appended during the await must not be
        dropped, which is what a plain gather-then-clear would do. Bounded on both axes
        so a page that keeps firing requests cannot hold us here forever.
        """
        for _ in range(rounds):
            if not self._pending:
                return
            pending, self._pending = self._pending, []
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=self.body_timeout + 5,
                )
            except asyncio.TimeoutError:
                for task in pending:
                    task.cancel()
                return

    # ------------------------------------------------------------------ navigation

    async def settle(self, url):
        """Load a page and wait out the bot check, reloading if it doesn't clear."""
        deadline = time.monotonic() + self.settle_timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            await self.page.goto(url, wait_until="domcontentloaded")

            until = time.monotonic() + min(20, deadline - time.monotonic())
            while time.monotonic() < until:
                await asyncio.sleep(2)
                try:
                    html = await self.page.content()
                except Exception:
                    continue  # mid-navigation; the challenge page is redirecting
                if "__UNIVERSAL_DATA_FOR_REHYDRATION__" in html:
                    if attempt > 1:
                        self.log(f"cleared the bot check on attempt {attempt}")
                    return html

            if time.monotonic() < deadline:
                self.log(f"bot check still up after {attempt} attempt(s), reloading...")

        raise PageBlocked(f"{url} never loaded within {self.settle_timeout}s")

    async def inline_data(self, url):
        """The __UNIVERSAL_DATA__ blob a TikTok page ships its own state in."""
        html = await self.settle(url)
        match = UNIVERSAL_DATA.search(html)
        if not match:
            raise PageBlocked(f"{url} loaded without inline data")
        return json.loads(match.group(1)).get("__DEFAULT_SCOPE__", {})

    async def harvest(self, url, path, limit, *, item_key="itemList", id_key="id",
                      scroll=True, idle_limit=4, prepare=None):
        """Open a page and collect the items it fetches from `path`, scrolling for more.

        `prepare` runs once after the page settles - some panels only issue their
        request after a click.
        """
        capture = {"path": path, "item_key": item_key, "id_key": id_key,
                   "items": [], "seen": set(), "exhausted": False}
        self._captures.append(capture)
        try:
            await self.settle(url)
            if prepare is not None:
                await prepare()

            idle = 0
            while len(capture["items"]) < limit and not capture["exhausted"] and idle < idle_limit:
                before = len(capture["items"])
                if scroll:
                    await self.page.mouse.wheel(0, 5000)
                await asyncio.sleep(2.5)
                await self._flush()
                idle = 0 if len(capture["items"]) > before else idle + 1

            await self._flush()
            return capture["items"][:limit]
        finally:
            self._captures.remove(capture)
