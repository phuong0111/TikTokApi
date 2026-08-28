"""Parsing, against real captured payloads.

Assertions read expected values out of the fixture rather than hardcoding them, so a
recapture does not invalidate the suite. The precedence cases below are hand-written
because they need two conflicting keys present at once.
"""

from datetime import datetime

from tiktokweb.models import (
    Author,
    Comment,
    Profile,
    Sound,
    Stats,
    UserResult,
    Video,
    _int,
    _timestamp,
    missing_fields,
    to_dict,
)


# ------------------------------------------------------------------- real payloads

def test_video_from_a_captured_item(fixture):
    item = fixture("video_items")[0]
    video = Video.from_raw(item)

    assert video.id == item["id"]
    assert video.description == (item.get("desc") or "")
    assert video.author.username == item["author"]["uniqueId"]
    assert video.url == f"https://www.tiktok.com/@{video.author.username}/video/{video.id}"
    assert video.raw is item
    assert isinstance(video.created, datetime)


def test_video_stats_come_through_as_ints(fixture):
    item = fixture("video_items")[0]
    stats = Video.from_raw(item).stats

    assert isinstance(stats.plays, int)
    assert isinstance(stats.likes, int)
    source = item.get("statsV2") or item.get("stats")
    assert stats.plays == int(source["playCount"])
    assert stats.likes == int(source["diggCount"])


def test_video_media_and_sound_are_populated(fixture):
    item = fixture("video_items")[0]
    video = Video.from_raw(item)

    assert video.media.duration == item["video"]["duration"]
    assert video.media.cover == item["video"]["cover"]
    assert video.sound.id == item["music"]["id"]


def test_every_captured_video_parses(fixture):
    for item in fixture("video_items"):
        video = Video.from_raw(item)
        assert video.id
        assert video.author.username


def test_profile_from_the_captured_user_detail_scope(fixture):
    user_info = fixture("user_detail")["webapp.user-detail"]["userInfo"]
    profile = Profile.from_raw(user_info)

    assert profile.username == user_info["user"]["uniqueId"]
    assert profile.sec_uid == user_info["user"]["secUid"]
    assert isinstance(profile.followers, int)
    assert profile.followers == int(user_info["stats"]["followerCount"])
    assert profile.raw is user_info


def test_video_from_the_captured_video_detail_scope(fixture):
    item = fixture("video_detail")["webapp.video-detail"]["itemInfo"]["itemStruct"]
    video = Video.from_raw(item)

    assert video.id == item["id"]
    assert video.author.username == item["author"]["uniqueId"]


def test_comment_from_a_captured_item(fixture):
    item = fixture("comment_items")[0]
    comment = Comment.from_raw(item)

    assert comment.id == item["cid"]
    assert comment.text == item["text"]
    assert comment.likes == int(item["digg_count"])
    assert comment.author.username == item["user"]["unique_id"]


def test_user_result_from_a_captured_search_hit(fixture):
    item = fixture("search_user_items")[0]
    result = UserResult.from_raw(item)

    info = item.get("user_info") or item.get("user") or item
    assert result.username == (info.get("uniqueId") or info.get("unique_id"))
    assert result.raw is item


def test_general_search_returns_mixed_blocks_and_parses_all_of_them(fixture):
    """General search does not return only videos, and resources.py does not check.

    A name query answers with user cards - `card_title` / `user_list` / `view_more`, no
    `item` key - and SearchResource.videos() maps every block through Video.from_raw()
    regardless, so those become Video objects with id=None. Callers filter on `.id`.

    This asserts the real contract: parsing never raises whatever the block type, and
    any hit that *does* carry `item` unwraps to a usable video. Deterministic coverage
    of the unwrap itself lives in test_resource_wiring.py, which uses synthetic hits
    because TikTok will not reliably serve video blocks on demand.
    """
    hits = fixture("search_general_items")
    assert hits

    parsed = [Video.from_raw(hit.get("item") or hit) for hit in hits]
    assert len(parsed) == len(hits)

    wrapped = [Video.from_raw(hit["item"]) for hit in hits if "item" in hit]
    assert all(video.id and video.author.username for video in wrapped)


# ---------------------------------------------------------------------- precedence

def test_statsv2_wins_over_stats():
    """statsV2 carries the same counters as strings and is the fresher of the two."""
    stats = Stats.from_raw({"stats": {"playCount": 1}, "statsV2": {"playCount": "999"}})
    assert stats.plays == 999


def test_stats_is_used_when_statsv2_is_absent():
    assert Stats.from_raw({"stats": {"playCount": 7}}).plays == 7


def test_stats_of_an_item_with_neither_key_is_all_none():
    assert Stats.from_raw({}) == Stats()


def test_challenges_win_over_text_extra_for_hashtags():
    video = Video.from_raw({
        "id": "1",
        "challenges": [{"title": "gym"}, {"title": "fitness"}],
        "textExtra": [{"hashtagName": "ignored"}],
    })
    assert video.hashtags == ["gym", "fitness"]


def test_text_extra_is_the_hashtag_fallback():
    video = Video.from_raw({"id": "1", "textExtra": [{"hashtagName": "gym"}]})
    assert video.hashtags == ["gym"]


def test_mentions_come_from_text_extra():
    video = Video.from_raw({
        "id": "1",
        "textExtra": [{"userUniqueId": "therock"}, {"hashtagName": "gym"}],
    })
    assert video.mentions == ["therock"]


def test_author_accepts_both_key_styles():
    assert Author.from_raw({"uniqueId": "a", "secUid": "s"}).username == "a"
    assert Author.from_raw({"unique_id": "a", "sec_uid": "s"}).username == "a"
    assert Author.from_raw({"unique_id": "a", "sec_uid": "s"}).sec_uid == "s"


def test_author_of_a_non_dict_is_empty_rather_than_an_error():
    assert Author.from_raw(None) == Author()
    assert Author.from_raw("nonsense") == Author()


def test_sound_of_an_item_without_music_is_empty():
    assert Sound.from_raw({}) == Sound()


# ------------------------------------------------------------------------ coercion

def test_int_coerces_and_gives_up_quietly():
    assert _int("42") == 42
    assert _int(42) == 42
    assert _int(None) is None
    assert _int("nonsense") is None
    assert _int({}) is None


def test_timestamp_coerces_and_gives_up_quietly():
    assert _timestamp(1600000000) == datetime.fromtimestamp(1600000000)
    assert _timestamp("1600000000") == datetime.fromtimestamp(1600000000)
    assert _timestamp(None) is None
    assert _timestamp("nonsense") is None


# ------------------------------------------------------------------ to_dict/missing

def test_to_dict_drops_raw_by_default(fixture):
    out = to_dict(Video.from_raw(fixture("video_items")[0]))
    assert "raw" not in out
    assert "raw" not in out["author"]


def test_to_dict_keeps_raw_when_asked(fixture):
    item = fixture("video_items")[0]
    out = to_dict(Video.from_raw(item), raw=True)
    assert out["raw"]["id"] == item["id"]


def test_to_dict_renders_datetimes_as_isoformat(fixture):
    out = to_dict(Video.from_raw(fixture("video_items")[0]))
    assert out["created"] == datetime.fromisoformat(out["created"]).isoformat()


def test_missing_fields_reports_empty_paths_including_nested_ones():
    video = Video(id="1", description="", hashtags=[],
                  author=Author(username="a"), stats=Stats(plays=5))
    gaps = set(missing_fields(video))

    assert "description" in gaps
    assert "hashtags" in gaps
    assert "author.nickname" in gaps
    assert "stats.likes" in gaps
    assert "id" not in gaps
    assert "author.username" not in gaps
    assert "stats.plays" not in gaps
    assert not any(g.startswith("raw") for g in gaps)
