"""URL and id parsing - the part of the resource layer that needs no session at all."""

import pytest

from tiktokweb.resources import (
    HashtagResource,
    SoundResource,
    UserResource,
    VideoResource,
)


def test_user_url_and_at_stripping():
    assert UserResource(None, "therock").url == "https://www.tiktok.com/@therock"
    assert UserResource(None, "@therock").username == "therock"


def test_hashtag_url_and_hash_stripping():
    assert HashtagResource(None, "gym").url == "https://www.tiktok.com/tag/gym"
    assert HashtagResource(None, "#gym").name == "gym"


def test_sound_url_is_slug_then_id():
    assert SoundResource(None, 12345).url == "https://www.tiktok.com/music/sound-12345"
    assert SoundResource(None, 12345, "my-song").url == "https://www.tiktok.com/music/my-song-12345"


def test_sound_id_is_coerced_to_string():
    assert SoundResource(None, 12345).id == "12345"


def test_video_from_full_url_extracts_the_id():
    video = VideoResource(None, "https://www.tiktok.com/@therock/video/7123456789012345678")
    assert video.id == "7123456789012345678"
    assert video.url == "https://www.tiktok.com/@therock/video/7123456789012345678"


def test_video_from_share_link_has_no_id_until_resolved():
    video = VideoResource(None, "https://vm.tiktok.com/ZMabcdefg/")
    assert video.id is None
    assert video.url == "https://vm.tiktok.com/ZMabcdefg/"


def test_video_from_id_and_username_builds_the_canonical_url():
    video = VideoResource(None, "7123456789012345678", username="@therock")
    assert video.id == "7123456789012345678"
    assert video.url == "https://www.tiktok.com/@therock/video/7123456789012345678"


def test_video_from_bare_id_without_username_is_an_error():
    with pytest.raises(ValueError, match="username"):
        VideoResource(None, "7123456789012345678")
