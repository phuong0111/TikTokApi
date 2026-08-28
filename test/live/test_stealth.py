"""The vendored stealth layer, checked against about:blank - never touches TikTok.

stealth_async is load-bearing: without it pages load fine but never issue their data
requests, so info() keeps working while every harvest() returns nothing. If these fail,
collection is about to go quietly empty across the board.
"""

import asyncio

import pytest
from playwright.async_api import async_playwright

from tiktokweb import cookies as cookie_utils
from tiktokweb import stealthtest


async def _run(case):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False, args=["--headless=new"],
        executable_path=cookie_utils.find_chrome(None))
    try:
        await case(browser)
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.parametrize("case", stealthtest.CASES, ids=lambda c: c.__name__)
def test_stealth_case(case):
    """A browser per case - they load about:blank, so this is cheap."""
    asyncio.run(_run(case))
