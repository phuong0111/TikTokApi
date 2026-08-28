"""What each resource asks the session for.

Endpoint paths, scope keys and item_key/id_key are the things that break silently when
TikTok moves something: collection returns nothing and looks like ordinary flakiness.
"""

import pytest

from tiktokweb.models import Comment, Profile, UserResult, Video

VIDEO_URL = "https://www.tiktok.com/@therock/video/7123456789012345678"


async def drain(iterator):
    return [item async for item in iterator]


# --------------------------------------------------------------------------- inline

async def test_user_info_reads_the_user_detail_scope(fake_client, fixture):
    client, session = fake_client(inline=fixture("user_detail"))

    profile = await client.user("therock").info()

    assert isinstance(profile, Profile)
    assert profile.username
    assert session.calls == [("inline_data", "https://www.tiktok.com/@therock")]


async def test_user_info_survives_a_missing_scope_key(fake_client):
    client, _ = fake_client(inline={})
    profile = await client.user("therock").info()
    assert profile == Profile(raw={})


async def test_video_info_reads_the_video_detail_scope(fake_client, fixture):
    client, session = fake_client(inline=fixture("video_detail"))

    video = await client.video(VIDEO_URL).info()

    assert isinstance(video, Video)
    assert video.id
    assert session.calls == [("inline_data", VIDEO_URL)]


async def test_sound_info_reads_the_music_detail_scope(fake_client):
    client, session = fake_client(inline={"webapp.music-detail": {"musicInfo": {"id": "1"}}})

    info = await client.sound("12345").info()

    assert info == {"musicInfo": {"id": "1"}}
    assert session.calls == [("inline_data", "https://www.tiktok.com/music/sound-12345")]


# -------------------------------------------------------------------------- harvest

async def test_user_videos_harvests_post_item_list(fake_client, fixture):
    items = fixture("video_items")
    client, session = fake_client(items=items)

    videos = await drain(client.user("therock").videos(limit=3))

    assert all(isinstance(v, Video) for v in videos)
    assert [v.id for v in videos] == [i["id"] for i in items[:3]]
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/@therock", "/api/post/item_list", 3,
        "itemList", "id")


async def test_hashtag_videos_harvest_challenge_item_list(fake_client, fixture):
    client, session = fake_client(items=fixture("video_items"))

    await drain(client.hashtag("#gym").videos(limit=5))

    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/tag/gym", "/api/challenge/item_list", 5,
        "itemList", "id")


async def test_sound_videos_harvest_music_item_list(fake_client, fixture):
    client, session = fake_client(items=fixture("video_items"))

    await drain(client.sound("12345").videos(limit=5))

    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/music/sound-12345", "/api/music/item_list", 5,
        "itemList", "id")


async def test_related_videos_harvest_related_item_list(fake_client, fixture):
    client, session = fake_client(items=fixture("video_items"))

    await drain(client.video(VIDEO_URL).related(limit=4))

    assert session.harvest_call() == (
        "harvest", VIDEO_URL, "/api/related/item_list", 4, "itemList", "id")


async def test_trending_harvests_recommend_item_list_from_foryou(fake_client, fixture):
    """trending lives on the client rather than on a resource."""
    client, session = fake_client(items=fixture("video_items"))

    videos = await drain(client.trending(limit=5))

    assert all(isinstance(v, Video) for v in videos)
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/foryou", "/api/recommend/item_list", 5,
        "itemList", "id")


# --------------------------------------------------------------------------- search

async def test_search_users_uses_user_list_with_no_id_key(fake_client, fixture):
    """Search hits carry no stable id, hence id_key=None."""
    client, session = fake_client(items=fixture("search_user_items"))

    results = await drain(client.search.users("therock", limit=5))

    assert all(isinstance(r, UserResult) for r in results)
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/search/user?q=therock", "/api/search/user", 5,
        "user_list", None)


async def test_search_videos_uses_the_general_endpoint(fake_client, fixture):
    client, session = fake_client(items=fixture("search_general_items"))

    videos = await drain(client.search.videos("gym", limit=5))

    assert all(isinstance(v, Video) for v in videos)
    assert session.harvest_call() == (
        "harvest", "https://www.tiktok.com/search?q=gym", "/api/search/general", 5,
        "data", None)


async def test_search_videos_unwraps_the_general_search_wrapper(fake_client):
    """General search nests the video under "item"; a bare hit must still parse."""
    client, _ = fake_client(items=[
        {"type": 1, "item": {"id": "wrapped", "author": {"uniqueId": "a"}}},
        {"id": "bare", "author": {"uniqueId": "b"}},
    ])

    videos = await drain(client.search.videos("gym", limit=5))

    assert [v.id for v in videos] == ["wrapped", "bare"]


# ------------------------------------------------------------------------- comments

async def test_comments_harvest_comment_list_keyed_on_cid(fake_client, fixture):
    client, session = fake_client(items=fixture("comment_items"), headless=False)

    comments = await drain(client.video(VIDEO_URL).comments(limit=5))

    assert all(isinstance(c, Comment) for c in comments)
    assert session.harvest_call() == (
        "harvest", VIDEO_URL, "/api/comment/list", 5, "comments", "cid")


async def test_comments_warn_when_the_session_is_headless(fake_client, fixture):
    """Headless chrome never paints, so the comment control never exists."""
    client, session = fake_client(items=fixture("comment_items"), headless=True)

    await drain(client.video(VIDEO_URL).comments(limit=5))

    assert any(call[0] == "log" and "headless" in call[1] for call in session.calls)


async def test_comments_retry_while_nothing_comes_back(fake_client):
    """Rendering is flaky run to run, so an empty result is retried, not accepted."""
    client, session = fake_client(items=[], headless=False)

    comments = await drain(client.video(VIDEO_URL).comments(limit=5, attempts=3))

    assert comments == []
    assert len([c for c in session.calls if c[0] == "harvest"]) == 3


# --------------------------------------------------------------------------- limits

async def test_limit_is_passed_through_and_honoured(fake_client, fixture):
    items = fixture("video_items")
    client, session = fake_client(items=items)

    videos = await drain(client.user("therock").videos(limit=2))

    assert len(videos) == 2
    assert session.harvest_call()[3] == 2
