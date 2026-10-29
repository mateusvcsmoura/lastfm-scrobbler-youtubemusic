from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from scrobbler.history import Play
from scrobbler.selection import day_bounds, estimate_timestamps, select_new

SP = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 29, 23, 0, tzinfo=SP)
LAST_RUN = NOW - timedelta(days=1)
NOW_TS = int(NOW.timestamp())


def play(key, played="Today", duration=200):
    return Play(
        key=key,
        title=f"Faixa {key}",
        artist=f"Artista {key}",
        album=None,
        duration=duration,
        played=played,
        video_type=None,
    )


def keys(plays):
    return [item.key for item in plays]


def test_empty_history_has_nothing_new():
    assert select_new([], ["a", "b"], LAST_RUN, NOW) == []
    assert select_new([], None, None, NOW) == []


def test_first_run_only_considers_today():
    plays = [play("a"), play("b"), play("c", "Yesterday"), play("d", "Last week")]
    assert keys(select_new(plays, None, None, NOW)) == ["a", "b"]


def test_unchanged_history_has_nothing_new():
    plays = [play("a"), play("b", "Yesterday")]
    assert select_new(plays, ["a", "b"], LAST_RUN, NOW) == []


def test_identifies_new_plays_above_previous_snapshot():
    plays = [play("x"), play("y"), play("a", "Yesterday"), play("b", "Yesterday")]
    assert keys(select_new(plays, ["a", "b", "c"], LAST_RUN, NOW)) == ["x", "y"]


def test_detects_legitimate_replay_of_older_song():
    plays = [play("c"), play("a", "Yesterday"), play("b", "Yesterday"), play("d", "Yesterday")]
    assert keys(select_new(plays, ["a", "b", "c", "d"], LAST_RUN, NOW)) == ["c"]


def test_replay_of_most_recent_song_is_indistinguishable():
    plays = [play("a"), play("b", "Yesterday")]
    assert select_new(plays, ["a", "b"], LAST_RUN, NOW) == []


def test_handles_history_truncated_at_its_limit():
    previous = [f"old{i}" for i in range(200)]
    plays = [play(f"new{i}") for i in range(30)]
    plays += [play(f"old{i}", "Yesterday") for i in range(170)]
    assert keys(select_new(plays, previous, LAST_RUN, NOW)) == [f"new{i}" for i in range(30)]


def test_tolerates_entries_removed_from_history():
    plays = [play("x"), play("a", "Yesterday"), play("c", "Yesterday"), play("d", "Yesterday")]
    assert keys(select_new(plays, ["a", "b", "c", "d"], LAST_RUN, NOW)) == ["x"]


def test_without_anchor_already_synced_yesterday_is_not_resent():
    plays = [play("a"), play("b", "Yesterday"), play("c", "Last week")]
    assert keys(select_new(plays, ["z1", "z2"], LAST_RUN, NOW)) == ["a"]


def test_without_anchor_yesterday_is_used_after_a_missed_day():
    plays = [play("a"), play("b", "Yesterday"), play("c", "Last week")]
    since = NOW - timedelta(days=2)
    assert keys(select_new(plays, ["z1", "z2"], since, NOW)) == ["a", "b"]


def test_skips_yesterday_entries_when_last_sync_was_today():
    since = NOW.replace(hour=10)
    plays = [play("a"), play("b", "Yesterday"), play("c", "Yesterday")]
    assert keys(select_new(plays, ["c"], since, NOW)) == ["a"]


def test_day_bounds_use_sao_paulo_midnight():
    start, end = day_bounds("Today", NOW)
    assert start == datetime(2026, 10, 29, tzinfo=SP)
    assert start.astimezone(ZoneInfo("UTC")).hour == 3
    assert end is None
    assert day_bounds("Yesterday", NOW) == (datetime(2026, 10, 28, tzinfo=SP), start)
    assert day_bounds("June 2026", NOW) == (None, None)


def test_estimates_back_to_back_plays_ending_now():
    stamps = estimate_timestamps([play("a", duration=200), play("b", duration=100)], LAST_RUN, NOW)
    assert stamps == [NOW_TS - 200, NOW_TS - 300]


def test_uses_default_duration_when_unknown():
    assert estimate_timestamps([play("a", duration=None)], LAST_RUN, NOW) == [NOW_TS - 180]


def test_yesterday_plays_stay_on_previous_day_in_sao_paulo():
    plays = [play("a"), play("b", "Yesterday"), play("c", "Yesterday")]
    stamps = estimate_timestamps(plays, LAST_RUN, NOW)
    midnight = int(datetime(2026, 10, 29, tzinfo=SP).timestamp())
    assert stamps[0] >= midnight
    assert int(LAST_RUN.timestamp()) <= stamps[2] < stamps[1] < midnight
    assert datetime.fromtimestamp(stamps[1], SP).date() == date(2026, 10, 28)


def test_spreads_plays_that_do_not_fit_since_last_sync():
    since = NOW - timedelta(minutes=30)
    stamps = estimate_timestamps([play(str(i), duration=300) for i in range(20)], since, NOW)
    assert len(stamps) == 20
    assert all(int(since.timestamp()) < stamp < NOW_TS for stamp in stamps)
    assert stamps == sorted(stamps, reverse=True)
    assert len(set(stamps)) == 20


def test_timestamps_are_strictly_decreasing_across_sections():
    plays = [play("a"), play("b", "Yesterday"), play("c", "This week"), play("d", "June 2026")]
    stamps = estimate_timestamps(plays, NOW - timedelta(days=30), NOW)
    assert all(newer > older for newer, older in zip(stamps, stamps[1:], strict=False))
    assert stamps[-1] >= NOW_TS - 13 * 24 * 3600
