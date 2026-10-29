from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scrobbler.history import Scrobble
from scrobbler.state import State, StateError, load_state, save_state

NOW = datetime(2026, 10, 29, 23, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


def test_missing_state_means_first_run(tmp_path):
    assert load_state(tmp_path / "state.json") is None


def test_round_trip_preserves_state(tmp_path):
    path = tmp_path / "nested" / "state.json"
    state = State(
        history=["a", "b"],
        synced_at=NOW,
        pending=[Scrobble("Artista", "Faixa", 1793311200, "Álbum", 215)],
    )
    save_state(path, state)
    assert load_state(path) == state
    assert [item.name for item in path.parent.iterdir()] == ["state.json"]


def test_corrupt_state_is_reported(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError):
        load_state(path)


def test_incomplete_state_is_reported(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version": 1, "history": "abc", "pending": []}', encoding="utf-8")
    with pytest.raises(StateError):
        load_state(path)


def test_unknown_version_is_reported(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        '{"version": 99, "history": [], "pending": [], "synced_at": "2026-10-29T23:00:00-03:00"}',
        encoding="utf-8",
    )
    with pytest.raises(StateError, match="Versão"):
        load_state(path)
