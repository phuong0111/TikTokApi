#!/usr/bin/env python3
"""Check that the stealth scripts actually run in the page.

    python -m tiktokweb.stealthtest

Unlike `selftest` this never touches TikTok - it loads about:blank in the same
browser `BrowserSession` uses and asserts the evasions took effect. The scripts
are injected before any site script runs, so if they throw there is nothing to
notice at runtime: collection just quietly degrades. This is the check that
notices.

Exit code is the number of failures.
"""

import asyncio
import sys

from playwright.async_api import async_playwright

from . import cookies as cookie_utils
from .stealth.stealth import StealthConfig, stealth_async


async def _stealthed_page(browser, config=None):
    """A page with stealth applied, plus the uncaught errors it raised."""
    context = await browser.new_context()
    page = await context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await stealth_async(page, config)
    await page.goto("about:blank")
    return page, errors


async def applies_without_errors(browser):
    """The scripts run to completion instead of dying on the first statement."""
    page, errors = await _stealthed_page(browser)
    await page.evaluate("1")  # let any init-script error surface
    assert not errors, f"stealth raised {len(errors)} uncaught error(s): {errors}"


async def shared_scope_reaches_evasions(browser):
    """`opts` and `utils` are visible to the scripts that are built on them.

    WebGL spoofing needs both, so a value that came from the config means the shared
    scope survived - which it does not when each script is injected separately. The
    vendor is set here rather than read from the default so this keeps testing the
    mechanism if the shipped default ever stops spoofing webgl.
    """
    config = StealthConfig(vendor="Test Vendor Inc.", webgl_vendor=True)
    page, _ = await _stealthed_page(browser, config)
    vendor = await page.evaluate("""() => {
        const gl = document.createElement('canvas').getContext('webgl');
        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
        return gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL);
    }""")
    assert vendor == "Test Vendor Inc.", f"opts never reached the evasion: {vendor!r}"


async def helpers_stay_off_window(browser):
    """The shared scope must not become a fingerprint of its own.

    A page that can read `window.utils` can detect the stealth layer far more
    cheaply than any of the tells it hides.
    """
    page, _ = await _stealthed_page(browser)
    leaked = await page.evaluate(
        "() => ['utils', 'opts'].filter(name => name in window)"
    )
    assert not leaked, f"stealth leaked globals: {leaked}"


CASES = [applies_without_errors, shared_scope_reaches_evasions, helpers_stay_off_window]


async def run_async(headless=True):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=False, args=["--headless=new"] if headless else None,
        executable_path=cookie_utils.find_chrome(None))
    failures = 0
    try:
        for case in CASES:
            try:
                await case(browser)
                print(f"PASS  {case.__name__}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL  {case.__name__}: {exc}")
    finally:
        await browser.close()
        await playwright.stop()
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return failures


def run(argv=None):
    sys.exit(asyncio.run(run_async()))


if __name__ == "__main__":
    run()
