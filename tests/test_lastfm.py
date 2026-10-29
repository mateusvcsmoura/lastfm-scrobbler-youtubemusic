from types import SimpleNamespace
from xml.dom import minidom

import pylast
import pytest

from scrobbler.history import Scrobble
from scrobbler.lastfm import Lastfm, LastfmAuthError, LastfmError, LastfmRejectedError

ACCEPTED = '<scrobble><ignoredMessage code="0"></ignoredMessage></scrobble>'
TOO_OLD = '<scrobble><ignoredMessage code="3">Timestamp too old</ignoredMessage></scrobble>'


def response(*scrobbles):
    return f'<lfm status="ok"><scrobbles>{"".join(scrobbles)}</scrobbles></lfm>'


@pytest.fixture
def api(monkeypatch):
    recorder = SimpleNamespace(calls=[], outcomes=[])

    class FakeRequest:
        def __init__(self, network, method, params=None):
            recorder.calls.append((method, params))

        def execute(self, cacheable=False):
            outcome = recorder.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return minidom.parseString(outcome)

    monkeypatch.setattr(pylast, "_Request", FakeRequest)
    return recorder


@pytest.fixture
def client():
    sleeps = []
    network = pylast.LastFMNetwork(api_key="key", api_secret="secret", session_key="session")
    lastfm = Lastfm(network, sleep=sleeps.append)
    lastfm.sleeps = sleeps
    return lastfm


SCROBBLES = [
    Scrobble("Artista", "Faixa 1", 1000, "Álbum", 200),
    Scrobble("Artista", "Faixa 2", 1200),
]


def test_sends_batch_with_metadata(api, client):
    api.outcomes.append(response(ACCEPTED, ACCEPTED))
    assert client.scrobble(SCROBBLES) == []
    method, params = api.calls[0]
    assert method == "track.scrobble"
    assert params == {
        "artist[0]": "Artista",
        "track[0]": "Faixa 1",
        "timestamp[0]": 1000,
        "album[0]": "Álbum",
        "duration[0]": 200,
        "artist[1]": "Artista",
        "track[1]": "Faixa 2",
        "timestamp[1]": 1200,
    }


def test_reports_scrobbles_ignored_by_lastfm(api, client):
    api.outcomes.append(response(ACCEPTED, TOO_OLD))
    ignored = client.scrobble(SCROBBLES)
    assert [(item.scrobble.title, item.code, item.reason) for item in ignored] == [
        ("Faixa 2", "3", "horário muito antigo")
    ]


def test_retries_temporary_failures_with_backoff(api, client):
    api.outcomes += [
        pylast.WSError(None, "16", "Temporarily unavailable"),
        pylast.NetworkError(None, OSError("timeout")),
        response(ACCEPTED, ACCEPTED),
    ]
    assert client.scrobble(SCROBBLES) == []
    assert client.sleeps == [10, 20]


def test_gives_up_after_limited_attempts(api, client):
    api.outcomes += [pylast.WSError(None, "11", "Service offline")] * 3
    with pytest.raises(LastfmError, match="11"):
        client.scrobble(SCROBBLES)
    assert len(api.calls) == 3


def test_does_not_retry_rejected_requests(api, client):
    api.outcomes.append(pylast.WSError(None, "6", "Invalid parameters"))
    with pytest.raises(LastfmRejectedError):
        client.scrobble(SCROBBLES)
    assert client.sleeps == []


def test_exhausted_retries_are_not_reported_as_rejection(api, client):
    api.outcomes += [pylast.WSError(None, "8", "Operation failed")] * 3
    with pytest.raises(LastfmError) as error:
        client.scrobble(SCROBBLES)
    assert not isinstance(error.value, LastfmRejectedError)


def test_authentication_failure_is_explicit(api, client):
    api.outcomes.append(pylast.WSError(None, "9", "Invalid session key"))
    with pytest.raises(LastfmAuthError, match="LASTFM_SESSION_KEY"):
        client.username()
    assert client.sleeps == []


def test_username_validates_session(api, client):
    api.outcomes.append('<lfm status="ok"><user><name>ouvinte</name></user></lfm>')
    assert client.username() == "ouvinte"
    assert api.calls[0][0] == "user.getInfo"


def test_rejects_oversized_batch(client):
    with pytest.raises(ValueError):
        client.scrobble([SCROBBLES[0]] * 51)
