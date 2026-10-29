from dataclasses import dataclass
from typing import Any

MIN_DURATION_SECONDS = 31

SKIPPED_VIDEO_TYPES = {
    "MUSIC_VIDEO_TYPE_PODCAST_EPISODE": "episódio de podcast",
    "MUSIC_VIDEO_TYPE_UGC": "vídeo enviado por usuário",
}


@dataclass(frozen=True)
class Play:
    key: str
    title: str
    artist: str
    album: str | None
    duration: int | None
    played: str
    video_type: str | None


@dataclass(frozen=True)
class Scrobble:
    artist: str
    title: str
    timestamp: int
    album: str | None = None
    duration: int | None = None


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _primary_artist(artists: Any) -> str:
    if not isinstance(artists, list):
        return ""
    for artist in artists:
        name = _text(artist.get("name")) if isinstance(artist, dict) else ""
        if name:
            return name
    return ""


def parse_play(entry: Any) -> Play | None:
    if not isinstance(entry, dict):
        return None
    title = _text(entry.get("title"))
    artist = _primary_artist(entry.get("artists"))
    album = entry.get("album")
    duration = entry.get("duration_seconds")
    video_type = entry.get("videoType")
    return Play(
        key=_text(entry.get("videoId")) or f"{artist}\n{title}".casefold(),
        title=title,
        artist=artist,
        album=(_text(album.get("name")) if isinstance(album, dict) else "") or None,
        duration=duration if type(duration) is int and duration > 0 else None,
        played=_text(entry.get("played")),
        video_type=video_type if isinstance(video_type, str) else None,
    )


def rejection_reason(play: Play) -> str | None:
    if not play.title:
        return "sem título"
    if not play.artist:
        return "sem artista"
    if play.video_type in SKIPPED_VIDEO_TYPES:
        return SKIPPED_VIDEO_TYPES[play.video_type]
    if play.duration is not None and play.duration < MIN_DURATION_SECONDS:
        return "duração de até 30 segundos"
    return None
