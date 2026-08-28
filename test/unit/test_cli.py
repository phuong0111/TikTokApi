"""The argument surface, and the one piece of dispatch logic in cli.run()."""

import sys

import pytest

from tiktokweb import cli, livetest


def parse(argv):
    return cli.build_parser().parse_args(argv)


def test_defaults():
    args = parse(["trending"])
    assert args.command == "trending"
    assert args.limit == 20
    assert args.headless is True
    assert args.raw is False
    assert args.check is False
    assert args.proxy is None


def test_no_headless_flag_clears_headless():
    assert parse(["--no-headless", "trending"]).headless is False


def test_user_subcommand_takes_a_username_and_info_only():
    args = parse(["user", "therock", "--info-only"])
    assert (args.username, args.info_only) == ("therock", True)


def test_video_subcommand_takes_a_url():
    assert parse(["video", "https://www.tiktok.com/@a/video/1"]).url == \
        "https://www.tiktok.com/@a/video/1"


def test_search_subcommand_takes_a_term():
    assert parse(["search", "gym"]).term == "gym"


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        parse([])


def test_selftest_dispatch_hands_livetest_the_remaining_argv(monkeypatch):
    """selftest has its own flag set, so cli must not parse or reorder its flags."""
    captured = {}

    def fake_run(argv=None):
        captured["argv"] = argv
        raise SystemExit(0)

    monkeypatch.setattr(livetest, "run", fake_run)
    monkeypatch.setattr(sys, "argv",
                        ["tiktokweb", "--limit", "5", "selftest", "--only", "trending"])

    with pytest.raises(SystemExit):
        cli.run()

    assert captured["argv"] == ["--limit", "5", "--only", "trending"]
