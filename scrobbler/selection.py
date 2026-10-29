import logging
from datetime import datetime, time, timedelta
from itertools import accumulate, groupby

from scrobbler.history import Play

TODAY = "Today"
YESTERDAY = "Yesterday"
ANCHOR_WINDOW = 20
DEFAULT_DURATION_SECONDS = 180
MAX_SCROBBLE_AGE = timedelta(days=13)

log = logging.getLogger(__name__)


def find_boundary(current: list[str], previous: list[str]) -> int | None:
    for boundary in range(len(current)):
        rest = current[boundary:]
        present = set(rest)
        expected = [key for key in previous if key in present]
        width = min(ANCHOR_WINDOW, len(rest), len(expected))
        if width and rest[:width] == expected[:width]:
            return boundary
    return None


def day_bounds(label: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    today = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    if label == TODAY:
        return today, None
    if label == YESTERDAY:
        return today - timedelta(days=1), today
    return None, None


def _played_after(play: Play, since: datetime | None, now: datetime) -> bool:
    _, end = day_bounds(play.played, now)
    return since is None or end is None or end > since


def select_new(
    plays: list[Play], previous: list[str] | None, since: datetime | None, now: datetime
) -> list[Play]:
    if previous is None:
        return [play for play in plays if play.played == TODAY]

    boundary = find_boundary([play.key for play in plays], previous)
    if boundary is None:
        log.warning(
            "Histórico atual não se alinha ao snapshot anterior; considerando apenas músicas "
            "de hoje e, se a última sincronização foi antes de ontem, músicas de ontem."
        )
        yesterday_start, _ = day_bounds(YESTERDAY, now)
        include_yesterday = since is None or since < yesterday_start
        candidates = [
            play
            for play in plays
            if play.played == TODAY or (play.played == YESTERDAY and include_yesterday)
        ]
    else:
        candidates = plays[:boundary]

    unknown = {play.played for play in candidates} - {TODAY, YESTERDAY}
    if unknown:
        log.warning("Seções do histórico sem data exata: %s", ", ".join(sorted(unknown)))
    return [play for play in candidates if _played_after(play, since, now)]


def estimate_timestamps(plays: list[Play], since: datetime | None, now: datetime) -> list[int]:
    floor = now - MAX_SCROBBLE_AGE
    if since is not None:
        floor = max(floor, since)
    cursor = int(now.timestamp())
    stamps: list[int] = []
    for label, group in groupby(plays, key=lambda play: play.played):
        durations = [play.duration or DEFAULT_DURATION_SECONDS for play in group]
        start, end = day_bounds(label, now)
        upper = cursor if end is None else min(cursor, int(end.timestamp()))
        lower = int(max(floor, start).timestamp()) if start else int(floor.timestamp())
        group_stamps = [upper - elapsed for elapsed in accumulate(durations)]
        if group_stamps[-1] < lower:
            step = max(1, (upper - lower) // (len(durations) + 1))
            group_stamps = [upper - step * (index + 1) for index in range(len(durations))]
        stamps.extend(group_stamps)
        cursor = group_stamps[-1]
    return stamps
