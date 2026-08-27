"""Typed views over TikTok's payloads.

Every model keeps `.raw`, so a key TikTok renames costs you a typed attribute but never
the data itself.
"""

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    try:
        return datetime.fromtimestamp(int(value))
    except (TypeError, ValueError, OSError):
        return None


@dataclass
class Stats:
    plays: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None

    @classmethod
    def from_raw(cls, data):
        # statsV2 carries the same counters as strings, and is the fresher of the two
        stats = data.get("statsV2") or data.get("stats") or {}
        return cls(_int(stats.get("playCount")), _int(stats.get("diggCount")),
                   _int(stats.get("commentCount")), _int(stats.get("shareCount")),
                   _int(stats.get("collectCount")))


@dataclass
class Author:
    username: Optional[str] = None
    nickname: Optional[str] = None
    user_id: Optional[str] = None
    sec_uid: Optional[str] = None
    verified: Optional[bool] = None
    signature: Optional[str] = None

    @classmethod
    def from_raw(cls, data):
        data = data if isinstance(data, dict) else {}
        return cls(data.get("uniqueId") or data.get("unique_id"), data.get("nickname"),
                   data.get("id") or data.get("uid"), data.get("secUid") or data.get("sec_uid"),
                   data.get("verified"), data.get("signature"))


@dataclass
class Media:
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    ratio: Optional[str] = None
    definition: Optional[str] = None
    format: Optional[str] = None
    cover: Optional[str] = None
    dynamic_cover: Optional[str] = None

    @classmethod
    def from_raw(cls, data):
        meta = data.get("video") or {}
        return cls(meta.get("duration"), meta.get("width"), meta.get("height"),
                   meta.get("ratio"), meta.get("definition"), meta.get("format"),
                   meta.get("cover"), meta.get("dynamicCover"))


@dataclass
class Sound:
    id: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    original: Optional[bool] = None
    duration: Optional[int] = None

    @classmethod
    def from_raw(cls, data):
        music = data.get("music") or {}
        return cls(music.get("id"), music.get("title"), music.get("authorName"),
                   music.get("original"), music.get("duration"))


@dataclass
class Video:
    id: Optional[str] = None
    url: Optional[str] = None
    created: Optional[datetime] = None
    description: str = ""
    author: Author = field(default_factory=Author)
    stats: Stats = field(default_factory=Stats)
    media: Media = field(default_factory=Media)
    sound: Sound = field(default_factory=Sound)
    hashtags: list = field(default_factory=list)
    mentions: list = field(default_factory=list)
    language: Optional[str] = None
    location: Optional[str] = None
    is_ad: Optional[bool] = None
    private: Optional[bool] = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, data):
        author = Author.from_raw(data.get("author"))
        extra = data.get("textExtra") or []
        # challenges is the richer source; textExtra is the fallback when it's absent
        tags = [c.get("title") for c in (data.get("challenges") or []) if c.get("title")]
        if not tags:
            tags = [e.get("hashtagName") for e in extra if e.get("hashtagName")]
        return cls(
            id=data.get("id"),
            url=f"https://www.tiktok.com/@{author.username}/video/{data.get('id')}",
            created=_timestamp(data.get("createTime")),
            description=data.get("desc") or "",
            author=author,
            stats=Stats.from_raw(data),
            media=Media.from_raw(data),
            sound=Sound.from_raw(data),
            hashtags=tags,
            mentions=[e.get("userUniqueId") for e in extra if e.get("userUniqueId")],
            language=data.get("textLanguage"),
            location=data.get("locationCreated"),
            is_ad=data.get("isAd"),
            private=data.get("privateItem"),
            raw=data,
        )

    def __str__(self):
        return f"Video({self.id} by @{self.author.username})"


@dataclass
class Profile:
    username: Optional[str] = None
    nickname: Optional[str] = None
    user_id: Optional[str] = None
    sec_uid: Optional[str] = None
    verified: Optional[bool] = None
    private: Optional[bool] = None
    region: Optional[str] = None
    signature: Optional[str] = None
    followers: Optional[int] = None
    following: Optional[int] = None
    likes: Optional[int] = None
    videos: Optional[int] = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, user_info):
        user_info = user_info or {}
        user = user_info.get("user") or {}
        stats = user_info.get("stats") or user_info.get("statsV2") or {}
        return cls(
            username=user.get("uniqueId"), nickname=user.get("nickname"),
            user_id=user.get("id"), sec_uid=user.get("secUid"),
            verified=user.get("verified"), private=user.get("privateAccount"),
            region=user.get("region"), signature=user.get("signature"),
            followers=_int(stats.get("followerCount")),
            following=_int(stats.get("followingCount")),
            likes=_int(stats.get("heartCount") or stats.get("heart")),
            videos=_int(stats.get("videoCount")),
            raw=user_info,
        )

    def __str__(self):
        return f"Profile(@{self.username}, {self.followers} followers)"


@dataclass
class Comment:
    id: Optional[str] = None
    text: str = ""
    likes: Optional[int] = None
    created: Optional[datetime] = None
    author: Author = field(default_factory=Author)
    reply_count: Optional[int] = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, data):
        return cls(
            id=data.get("cid"), text=data.get("text") or "",
            likes=_int(data.get("digg_count")), created=_timestamp(data.get("create_time")),
            author=Author.from_raw(data.get("user")),
            reply_count=_int(data.get("reply_comment_total")), raw=data,
        )

    def __str__(self):
        return f"Comment({self.text[:40]!r} +{self.likes})"


@dataclass
class UserResult:
    """A user as returned by search, which nests them differently to everywhere else."""

    username: Optional[str] = None
    nickname: Optional[str] = None
    user_id: Optional[str] = None
    sec_uid: Optional[str] = None
    verified: Optional[bool] = None
    followers: Optional[int] = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, data):
        info = data.get("user_info") or data.get("user") or data
        stats = data.get("stats") or {}
        return cls(
            username=info.get("uniqueId") or info.get("unique_id"),
            nickname=info.get("nickname"), user_id=info.get("id") or info.get("uid"),
            sec_uid=info.get("secUid") or info.get("sec_uid"),
            verified=info.get("verified"),
            followers=_int(stats.get("followerCount") or info.get("follower_count")),
            raw=data,
        )

    def __str__(self):
        return f"UserResult(@{self.username})"


def to_dict(model, *, raw=False):
    """Dataclass -> plain json-able dict. `raw` keeps TikTok's untouched payload."""
    def convert(value):
        if dataclasses.is_dataclass(value):
            return {k: convert(v) for k, v in dataclasses.asdict(value).items()
                    if raw or k != "raw"}
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    return convert(model)


def missing_fields(model, prefix=""):
    """Field paths that came back empty - absent for this item, or a key TikTok renamed."""
    data = to_dict(model) if dataclasses.is_dataclass(model) else model
    for key, value in data.items():
        if key == "raw":
            continue
        if isinstance(value, dict):
            yield from missing_fields(value, f"{prefix}{key}.")
        elif value is None or value == "" or value == []:
            yield prefix + key
