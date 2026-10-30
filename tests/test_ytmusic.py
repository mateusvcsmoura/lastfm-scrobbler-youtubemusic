import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests
from ytmusicapi import YTMusic
from ytmusicapi.auth.types import AuthType
from ytmusicapi.exceptions import YTMusicServerError, YTMusicUserError

from scrobbler import ytmusic
from scrobbler.ytmusic import (
    YouTubeMusicAuthError,
    YouTubeMusicError,
    fetch_history,
    parse_browser_auth,
)

NOW = datetime(2026, 10, 29, 23, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
HEADERS = {
    "accept": "*/*",
    "authorization": "SAPISIDHASH 1700000000_abcdef",
    "content-type": "application/json",
    "cookie": "SID=fake; __Secure-3PAPISID=fake-sapisid",
    "origin": "https://music.youtube.com",
    "x-goog-authuser": "0",
    "x-goog-visitor-id": "fake-visitor",
}


def test_accepts_browser_json_content():
    assert parse_browser_auth(json.dumps(HEADERS)) == HEADERS


def test_accepts_browser_json_path(tmp_path):
    path = tmp_path / "browser.json"
    path.write_text(json.dumps(HEADERS), encoding="utf-8")
    assert parse_browser_auth(str(path)) == HEADERS


def test_validated_auth_is_recognized_by_ytmusicapi_as_browser_auth():
    assert YTMusic(auth=parse_browser_auth(json.dumps(HEADERS))).auth_type == AuthType.BROWSER


def test_rejects_empty_auth():
    with pytest.raises(YouTubeMusicAuthError, match="__Secure-3PAPISID"):
        parse_browser_auth("{}")


def test_rejects_missing_authorization_header():
    headers = {key: value for key, value in HEADERS.items() if key != "authorization"}
    with pytest.raises(YouTubeMusicAuthError, match="SAPISIDHASH"):
        parse_browser_auth(json.dumps(headers))


def test_invalid_json_error_does_not_echo_secret():
    secret = '{"cookie": "__Secure-3PAPISID=very-secret-value"'
    with pytest.raises(YouTubeMusicAuthError) as error:
        parse_browser_auth(secret)
    assert "very-secret-value" not in str(error.value)


def test_unknown_path_error_does_not_echo_value():
    with pytest.raises(YouTubeMusicAuthError) as error:
        parse_browser_auth("SID=very-secret-value")
    assert "very-secret-value" not in str(error.value)


def fake_client(monkeypatch, outcome):
    created = []

    class FakeYTMusic:
        def __init__(self, auth, language):
            self.context = {"context": {"client": {"hl": language}}}
            created.append(self)

        def get_history(self):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(ytmusic, "YTMusic", FakeYTMusic)
    return created


def test_fetches_history_in_sao_paulo_timezone(monkeypatch):
    created = fake_client(monkeypatch, [{"videoId": "a"}])
    assert fetch_history(HEADERS, NOW) == [{"videoId": "a"}]
    assert created[0].context["context"]["client"] == {
        "hl": "en",
        "timeZone": "America/Sao_Paulo",
        "utcOffsetMinutes": -180,
    }


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (YTMusicServerError("Server returned HTTP 401: Unauthorized.\n"), YouTubeMusicAuthError),
        (YTMusicServerError(None), YouTubeMusicAuthError),
        (YTMusicUserError("Your cookie is missing __Secure-3PAPISID"), YouTubeMusicAuthError),
        (YTMusicServerError("Server returned HTTP 503: Unavailable.\n"), YouTubeMusicError),
        (requests.ConnectionError("down"), YouTubeMusicError),
        (KeyError("singleColumnBrowseResultsRenderer"), YouTubeMusicError),
        ({"unexpected": "shape"}, YouTubeMusicError),
    ],
)
def test_maps_failures_to_clear_errors(monkeypatch, outcome, expected):
    fake_client(monkeypatch, outcome)
    with pytest.raises(expected):
        fetch_history(HEADERS, NOW)


def test_server_outage_is_not_reported_as_auth_failure(monkeypatch):
    fake_client(monkeypatch, YTMusicServerError("Server returned HTTP 503: Unavailable.\n"))
    with pytest.raises(YouTubeMusicError) as error:
        fetch_history(HEADERS, NOW)
    assert not isinstance(error.value, YouTubeMusicAuthError)
