"""Getting and keeping a TikTok session.

TikTok answers logged-out sessions with empty payloads, so a real login is required.
`login()` drives a visible browser and captures the jar; `load()` reuses it afterwards.
"""

import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright

from .errors import LoginAborted
from .stealth import stealth_async

DEFAULT_STORE = Path("cookies.json")

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def find_chrome(explicit=None):
    """Locate an installed Chrome so playwright needs no browser download."""
    if explicit:
        return str(explicit)
    for candidate in CHROME_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def load(source):
    """Accept a browser cookie export: a json file, a json string, or a Cookie header."""
    if not source:
        return None

    text = source if isinstance(source, str) else str(source)
    try:
        path = Path(text).expanduser()
        if path.is_file():
            text = path.read_text()
    except OSError:  # the string is far too long to be a path
        pass

    text = text.strip()
    if not text:
        return None

    if text.startswith(("{", "[")):
        data = json.loads(text)
        if isinstance(data, list):  # a cookie-manager export
            return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
        if {"name", "value"} <= data.keys():  # a single exported record
            return {data["name"]: data["value"]}
        return {k: str(v) for k, v in data.items() if isinstance(v, (str, int, float))}

    jar = {}
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            name, value = part.split("=", 1)
            jar[name.strip()] = value.strip()
    return jar


def save(jar, store=DEFAULT_STORE):
    """Write the jar out at 0600 - it is a live session, equivalent to the password."""
    store = Path(store)
    store.write_text(json.dumps(jar, indent=2))
    store.chmod(0o600)
    return store


def is_logged_in(jar):
    return bool((jar or {}).get("sessionid"))


def to_playwright(jar):
    """A browser keeps these on the parent domain; anything else hides them from tiktok.com."""
    return [{"name": k, "value": v, "domain": ".tiktok.com", "path": "/"} for k, v in jar.items()]


async def login(store=DEFAULT_STORE, *, chrome=None, timeout=900, proxy=None, on_message=print):
    """Open a browser on TikTok, wait for a login, and save the resulting cookie jar."""
    on_message("opening a browser window - log in to TikTok there.")
    on_message(f"waiting up to {timeout}s; the window closes on its own once you're in.")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, executable_path=find_chrome(chrome),
                                           proxy=proxy)
        context = await browser.new_context()
        page = await context.new_page()
        await stealth_async(page)
        await page.goto("https://www.tiktok.com/login")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                jar = {c["name"]: c["value"] for c in await context.cookies()}
            except Exception:
                raise LoginAborted("browser closed before the login completed")

            if jar.get("sessionid"):
                on_message("logged in - settling the session...")
                # land on a normal page so ttwid/msToken are issued for a logged-in device
                await page.goto("https://www.tiktok.com/foryou")
                await asyncio.sleep(5)
                jar = {c["name"]: c["value"] for c in await context.cookies()}
                break

            await asyncio.sleep(2)
        else:
            await browser.close()
            raise LoginAborted(f"no login detected within {timeout}s")

        await browser.close()

    path = save(jar, store)
    on_message(f"captured {len(jar)} cookies -> {path}")
    return jar


async def ensure(source=DEFAULT_STORE, *, chrome=None, timeout=900, allow_login=True,
                 force_login=False, proxy=None, on_message=print):
    """Return a logged-in jar, running the interactive login only when needed."""
    store = Path(source) if not str(source).lstrip().startswith(("{", "[")) else DEFAULT_STORE

    if not force_login:
        jar = load(source)
        if is_logged_in(jar):
            # never echo the source itself - it may be a raw string containing sessionid
            on_message(f"using cached login from {store if store.is_file() else 'the given cookies'}")
            return jar
        if jar and not allow_login:
            return jar

    if not allow_login:
        return None
    return await login(store, chrome=chrome, timeout=timeout, proxy=proxy, on_message=on_message)
