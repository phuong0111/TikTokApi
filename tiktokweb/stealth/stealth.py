# -*- coding: utf-8 -*-
import json
from dataclasses import dataclass
from typing import Tuple, Optional, Dict

from playwright.async_api import Page as AsyncPage

from .js.chrome_app import chrome_app
from .js.chrome_csi import chrome_csi
from .js.chrome_hairline import chrome_hairline
from .js.chrome_load_times import chrome_load_times
from .js.chrome_runtime import chrome_runtime
from .js.generate_magic_arrays import generate_magic_arrays
from .js.iframe_contentWindow import iframe_contentWindow
from .js.media_codecs import media_codecs
from .js.navigator_hardwareConcurrency import navigator_hardwareConcurrency
from .js.navigator_languages import navigator_languages
from .js.navigator_permissions import navigator_permissions
from .js.navigator_platform import navigator_platform
from .js.navigator_plugins import navigator_plugins
from .js.navigator_userAgent import navigator_userAgent
from .js.navigator_vendor import navigator_vendor
from .js.webgl_vendor import webgl_vendor
from .js.window_outerdimensions import window_outerdimensions
from .js.utils import utils

SCRIPTS: Dict[str, str] = {
    "chrome_csi": chrome_csi,
    "chrome_app": chrome_app,
    "chrome_runtime": chrome_runtime,
    "chrome_load_times": chrome_load_times,
    "chrome_hairline": chrome_hairline,
    "generate_magic_arrays": generate_magic_arrays,
    "iframe_content_window": iframe_contentWindow,
    "media_codecs": media_codecs,
    "navigator_vendor": navigator_vendor,
    "navigator_plugins": navigator_plugins,
    "navigator_permissions": navigator_permissions,
    "navigator_languages": navigator_languages,
    "navigator_platform": navigator_platform,
    "navigator_user_agent": navigator_userAgent,
    "navigator_hardware_concurrency": navigator_hardwareConcurrency,
    "outerdimensions": window_outerdimensions,
    "utils": utils,
    "webdriver": "delete Object.getPrototypeOf(navigator).webdriver",
    "webgl_vendor": webgl_vendor,
}


@dataclass
class StealthConfig:
    """
    Playwright stealth configuration that applies stealth strategies to playwright page objects.
    The stealth strategies are contained in ./js package and are basic javascript scripts that are executed
    on every page.goto() called.
    Note:
        Playwright evaluates every add_init_script in its own scope, so the scripts are
        combined here instead: `preamble` defines the `opts`/`utils` scope the evasions
        are written against, and they only see it because they ship as one script.
        Scripts can be extended by overriding the enabled_scripts generator:
        ```
        @property
        def enabled_scripts():
            yield 'console.log("first script")'
            yield from super().enabled_scripts()
            yield 'console.log("last script")'
        ```
    """

    # load script options
    webdriver: bool = True
    webgl_vendor: bool = True
    chrome_app: bool = True
    chrome_csi: bool = True
    chrome_load_times: bool = True
    chrome_runtime: bool = True
    iframe_content_window: bool = True
    media_codecs: bool = True
    navigator_hardware_concurrency: int = 4
    navigator_languages: bool = False
    navigator_permissions: bool = True
    navigator_platform: bool = True
    navigator_plugins: bool = True
    navigator_user_agent: bool = False
    navigator_vendor: bool = False
    outerdimensions: bool = True
    hairline: bool = True

    # options
    vendor: str = "Intel Inc."
    renderer: str = "Intel Iris OpenGL Engine"
    nav_vendor: str = "Google Inc."
    nav_user_agent: str = None
    nav_platform: str = None
    languages: Tuple[str] = ("en-US", "en")
    runOnInsecureOrigins: Optional[bool] = None

    @property
    def preamble(self):
        """The shared scope every evasion below is written against."""
        opts = json.dumps(
            {
                "webgl_vendor": self.vendor,
                "webgl_renderer": self.renderer,
                "navigator_vendor": self.nav_vendor,
                "navigator_platform": self.nav_platform,
                "navigator_user_agent": self.nav_user_agent,
                "languages": list(self.languages),
                "runOnInsecureOrigins": self.runOnInsecureOrigins,
            }
        )
        # defined options constant
        yield f"const opts = {opts}"
        # init utils and generate_magic_arrays helper
        yield SCRIPTS["utils"]
        yield SCRIPTS["generate_magic_arrays"]

    @property
    def enabled_scripts(self):
        if self.chrome_app:
            yield SCRIPTS["chrome_app"]
        if self.chrome_csi:
            yield SCRIPTS["chrome_csi"]
        if self.hairline:
            yield SCRIPTS["chrome_hairline"]
        if self.chrome_load_times:
            yield SCRIPTS["chrome_load_times"]
        if self.chrome_runtime:
            yield SCRIPTS["chrome_runtime"]
        if self.iframe_content_window:
            yield SCRIPTS["iframe_content_window"]
        if self.media_codecs:
            yield SCRIPTS["media_codecs"]
        if self.navigator_languages:
            yield SCRIPTS["navigator_languages"]
        if self.navigator_permissions:
            yield SCRIPTS["navigator_permissions"]
        if self.navigator_platform:
            yield SCRIPTS["navigator_platform"]
        if self.navigator_plugins:
            yield SCRIPTS["navigator_plugins"]
        if self.navigator_user_agent:
            yield SCRIPTS["navigator_user_agent"]
        if self.navigator_vendor:
            yield SCRIPTS["navigator_vendor"]
        if self.webdriver:
            yield SCRIPTS["webdriver"]
        if self.outerdimensions:
            yield SCRIPTS["outerdimensions"]
        if self.webgl_vendor:
            yield SCRIPTS["webgl_vendor"]


def build_script(config: StealthConfig = None) -> str:
    """The evasions as one script sharing one scope.

    Wrapped in an IIFE so `opts` and `utils` stay off `window` - a page that can read
    them detects the stealth layer more cheaply than any tell it hides. Each evasion is
    isolated in turn because several (chrome_load_times, chrome_runtime) throw by design
    when they detect a real Chrome, and a bare throw would abort every script after it.
    """
    config = config or StealthConfig()
    evasions = "\n".join(
        f"try {{ (() => {{\n{script}\n}})() }} catch (e) {{}}"
        for script in config.enabled_scripts
    )
    # the preamble stays unguarded: if it breaks, every evasion silently does too, so
    # that has to surface as an uncaught error rather than being swallowed here
    return "(() => {\n" + "\n".join(config.preamble) + "\n" + evasions + "\n})()"


async def stealth_async(page: AsyncPage, config: StealthConfig = None):
    """stealth the page"""
    await page.add_init_script(build_script(config))
