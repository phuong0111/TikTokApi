"""cookies.load accepts a lot of shapes; each one is a way a user actually pastes a session."""

import json
import stat

from tiktokweb import cookies


def test_load_from_json_file(tmp_path):
    path = tmp_path / "jar.json"
    path.write_text(json.dumps({"sessionid": "abc", "ttwid": "xyz"}))
    assert cookies.load(str(path)) == {"sessionid": "abc", "ttwid": "xyz"}


def test_load_from_json_string():
    assert cookies.load('{"sessionid": "abc"}') == {"sessionid": "abc"}


def test_load_from_cookie_header():
    header = "sessionid=abc; ttwid=xyz; msToken=q1"
    assert cookies.load(header) == {"sessionid": "abc", "ttwid": "xyz", "msToken": "q1"}


def test_load_from_cookie_manager_list_export():
    export = json.dumps([
        {"name": "sessionid", "value": "abc", "domain": ".tiktok.com"},
        {"name": "ttwid", "value": "xyz"},
        {"domain": "ignored, no name or value"},
    ])
    assert cookies.load(export) == {"sessionid": "abc", "ttwid": "xyz"}


def test_load_from_single_exported_record():
    assert cookies.load('{"name": "sessionid", "value": "abc"}') == {"sessionid": "abc"}


def test_load_coerces_non_string_scalars():
    assert cookies.load('{"sessionid": "abc", "count": 3}') == {"sessionid": "abc", "count": "3"}


def test_load_drops_nested_values():
    assert cookies.load('{"sessionid": "abc", "nested": {"a": 1}}') == {"sessionid": "abc"}


def test_load_returns_none_on_empty_input():
    assert cookies.load("") is None
    assert cookies.load(None) is None
    assert cookies.load("   ") is None


def test_save_writes_0600(tmp_path):
    path = cookies.save({"sessionid": "abc"}, tmp_path / "jar.json")
    assert json.loads(path.read_text()) == {"sessionid": "abc"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_is_logged_in_requires_sessionid():
    assert cookies.is_logged_in({"sessionid": "abc"})
    assert not cookies.is_logged_in({"ttwid": "xyz"})
    assert not cookies.is_logged_in({})
    assert not cookies.is_logged_in(None)


def test_to_playwright_puts_cookies_on_the_parent_domain():
    out = cookies.to_playwright({"sessionid": "abc"})
    assert out == [{"name": "sessionid", "value": "abc", "domain": ".tiktok.com", "path": "/"}]
