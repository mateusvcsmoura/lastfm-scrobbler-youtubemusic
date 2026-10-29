from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scrobbler.lastfm import Ignored, LastfmAuthError, LastfmError, LastfmRejectedError
from scrobbler.state import StateError, load_state
from scrobbler.sync import run_sync

SP = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 29, 23, 0, tzinfo=SP)


def raw(video_id, played="Today", **overrides):
    entry = {
        "videoId": video_id,
        "title": f"Faixa {video_id}",
        "artists": [{"name": "Artista", "id": "UC1"}],
        "album": {"name": "Álbum", "id": "MPRE1"},
        "duration_seconds": 200,
        "played": played,
        "videoType": "MUSIC_VIDEO_TYPE_ATV",
    }
    entry.update(overrides)
    return entry


class FakeLastfm:
    def __init__(self, fail=None, ignore_titles=(), auth_error=False):
        self.batches = []
        self.fail = fail
        self.ignore_titles = ignore_titles
        self.auth_error = auth_error

    def username(self):
        if self.auth_error:
            raise LastfmAuthError("credenciais inválidas")
        return "ouvinte"

    def scrobble(self, batch):
        if self.fail:
            raise self.fail
        self.batches.append(list(batch))
        return [
            Ignored(item, "1", "artista filtrado pelo Last.fm")
            for item in batch
            if item.title in self.ignore_titles
        ]

    def titles(self):
        return [item.title for batch in self.batches for item in batch]


def sync(history, lastfm, state_path, now=NOW, dry_run=False):
    return run_sync(lambda: history, lastfm, state_path, now, dry_run)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "state" / "state.json"


def test_first_run_sends_only_today_and_saves_snapshot(state_path):
    lastfm = FakeLastfm()
    history = [raw("b"), raw("a"), raw("old", "Yesterday")]
    summary = sync(history, lastfm, state_path)
    assert lastfm.titles() == ["Faixa a", "Faixa b"]
    assert (summary.found, summary.new, summary.already_processed, summary.accepted) == (3, 2, 1, 2)
    state = load_state(state_path)
    assert state.history == ["b", "a", "old"]
    assert state.pending == []
    assert state.synced_at == NOW


def test_unchanged_history_is_not_sent_again(state_path):
    history = [raw("b"), raw("a")]
    sync(history, FakeLastfm(), state_path)
    lastfm = FakeLastfm()
    summary = sync(history, lastfm, state_path, NOW + timedelta(days=1))
    assert lastfm.batches == []
    assert (summary.new, summary.already_processed) == (0, 2)


def test_manual_run_followed_by_scheduled_run_sends_only_new_plays(state_path):
    sync([raw("b"), raw("a")], FakeLastfm(), state_path, NOW.replace(hour=15))
    lastfm = FakeLastfm()
    sync([raw("d"), raw("c"), raw("b"), raw("a")], lastfm, state_path)
    assert lastfm.titles() == ["Faixa c", "Faixa d"]


def test_replayed_song_is_scrobbled_again(state_path):
    sync([raw("b"), raw("a")], FakeLastfm(), state_path, NOW - timedelta(days=1))
    lastfm = FakeLastfm()
    sync([raw("a"), raw("b", "Yesterday")], lastfm, state_path)
    assert lastfm.titles() == ["Faixa a"]


def test_failed_delivery_keeps_pending_and_sends_it_first_next_time(state_path):
    summary = sync([raw("b"), raw("a")], FakeLastfm(fail=LastfmError("offline")), state_path)
    assert summary.pending == 2
    assert [item.title for item in load_state(state_path).pending] == ["Faixa a", "Faixa b"]

    lastfm = FakeLastfm()
    summary = sync([raw("c"), raw("b"), raw("a")], lastfm, state_path, NOW + timedelta(hours=1))
    assert lastfm.titles() == ["Faixa a", "Faixa b", "Faixa c"]
    assert (summary.carried_over, summary.accepted, summary.pending) == (2, 3, 0)
    assert load_state(state_path).pending == []


def test_scrobbles_are_sent_oldest_first_with_increasing_timestamps(state_path):
    lastfm = FakeLastfm()
    sync([raw("c"), raw("b"), raw("a")], lastfm, state_path)
    stamps = [item.timestamp for item in lastfm.batches[0]]
    assert stamps == sorted(stamps)
    assert stamps[-1] <= int(NOW.timestamp())


def test_large_backlog_is_sent_in_batches_of_fifty(state_path):
    lastfm = FakeLastfm()
    sync([raw(f"v{i}", duration_seconds=60) for i in range(120)], lastfm, state_path)
    assert [len(batch) for batch in lastfm.batches] == [50, 50, 20]


def test_progress_is_saved_after_each_successful_batch(state_path):
    class FailsOnSecondBatch(FakeLastfm):
        def scrobble(self, batch):
            if self.batches:
                raise LastfmError("offline")
            return super().scrobble(batch)

    summary = sync(
        [raw(f"v{i}", duration_seconds=60) for i in range(70)], FailsOnSecondBatch(), state_path
    )
    assert (summary.accepted, summary.pending) == (50, 20)
    assert len(load_state(state_path).pending) == 20


def test_rejected_scrobble_does_not_block_the_queue(state_path):
    class RejectsOneTrack(FakeLastfm):
        def scrobble(self, batch):
            if any(item.title == "Faixa bad" for item in batch):
                raise LastfmRejectedError("código 6")
            return super().scrobble(batch)

    lastfm = RejectsOneTrack()
    summary = sync([raw("c"), raw("bad"), raw("a")], lastfm, state_path)
    assert lastfm.titles() == ["Faixa a", "Faixa c"]
    assert (summary.accepted, summary.ignored, summary.pending) == (2, 1, 0)
    assert load_state(state_path).pending == []


def test_dry_run_neither_sends_nor_writes_state(state_path):
    lastfm = FakeLastfm()
    summary = sync([raw("a")], lastfm, state_path, dry_run=True)
    assert lastfm.batches == []
    assert not state_path.exists()
    assert summary.pending == 1


def test_dry_run_keeps_existing_state_untouched(state_path):
    sync([raw("a")], FakeLastfm(), state_path)
    before = state_path.read_bytes()
    sync([raw("b"), raw("a")], FakeLastfm(), state_path, NOW + timedelta(hours=1), dry_run=True)
    assert state_path.read_bytes() == before


def test_lastfm_auth_failure_stops_before_touching_state(state_path):
    with pytest.raises(LastfmAuthError):
        sync([raw("a")], FakeLastfm(auth_error=True), state_path)
    assert not state_path.exists()


def test_empty_history_keeps_previous_snapshot(state_path):
    sync([raw("b"), raw("a")], FakeLastfm(), state_path)
    lastfm = FakeLastfm()
    summary = sync([], lastfm, state_path, NOW + timedelta(hours=1))
    assert lastfm.batches == []
    assert summary.found == 0
    assert load_state(state_path).history == ["b", "a"]


def test_invalid_entries_are_skipped_and_counted(state_path):
    lastfm = FakeLastfm()
    history = [
        raw("pod", videoType="MUSIC_VIDEO_TYPE_PODCAST_EPISODE"),
        raw("notitle", title=""),
        "garbage",
        raw("ok"),
    ]
    summary = sync(history, lastfm, state_path)
    assert lastfm.titles() == ["Faixa ok"]
    assert (summary.found, summary.new, summary.skipped) == (3, 3, 2)


def test_ignored_scrobbles_are_counted_and_not_retried(state_path):
    lastfm = FakeLastfm(ignore_titles={"Faixa a"})
    summary = sync([raw("b"), raw("a")], lastfm, state_path)
    assert (summary.accepted, summary.ignored, summary.pending) == (1, 1, 0)
    assert load_state(state_path).pending == []


def test_corrupt_state_aborts_without_sending(state_path):
    state_path.parent.mkdir(parents=True)
    state_path.write_text("corrompido", encoding="utf-8")
    lastfm = FakeLastfm()
    with pytest.raises(StateError):
        sync([raw("a")], lastfm, state_path)
    assert lastfm.batches == []
