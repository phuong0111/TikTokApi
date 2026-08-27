"""Exceptions raised by tiktokweb."""


class TikTokWebError(Exception):
    """Base for every error this package raises."""


class LoginAborted(TikTokWebError):
    """The interactive login window was closed or timed out."""


class PageBlocked(TikTokWebError):
    """A page never got past TikTok's bot check within the settle timeout."""


class NotLoggedIn(TikTokWebError):
    """No usable session. TikTok serves logged-out sessions empty data."""
