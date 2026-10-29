from scrobbler.history import Play, parse_play, rejection_reason


def raw(**overrides):
    entry = {
        "videoId": "abc123",
        "title": "  Garota   de Ipanema ",
        "artists": [{"name": " Tom Jobim ", "id": "UC1"}, {"name": "Vinicius", "id": "UC2"}],
        "album": {"name": "Getz/Gilberto", "id": "MPRE1"},
        "duration": "5:24",
        "duration_seconds": 324,
        "played": "Today",
        "videoType": "MUSIC_VIDEO_TYPE_ATV",
    }
    entry.update(overrides)
    return entry


def test_normalizes_metadata():
    assert parse_play(raw()) == Play(
        key="abc123",
        title="Garota de Ipanema",
        artist="Tom Jobim",
        album="Getz/Gilberto",
        duration=324,
        played="Today",
        video_type="MUSIC_VIDEO_TYPE_ATV",
    )


def test_uses_first_named_artist_even_without_id():
    play = parse_play(raw(artists=[{"name": "  ", "id": "UC1"}, {"name": "Upload", "id": None}]))
    assert play.artist == "Upload"


def test_tolerates_missing_or_malformed_fields():
    play = parse_play(
        {"title": None, "artists": None, "album": "x", "duration_seconds": True, "played": 3}
    )
    assert play.title == ""
    assert play.artist == ""
    assert play.album is None
    assert play.duration is None
    assert play.played == ""
    assert play.video_type is None


def test_ignores_non_dict_entries():
    assert parse_play(None) is None
    assert parse_play(["title"]) is None


def test_same_title_from_different_artists_are_different_songs():
    first = parse_play(raw(videoId=None, artists=[{"name": "Artista A"}], title="Intro"))
    second = parse_play(raw(videoId=None, artists=[{"name": "Artista B"}], title="Intro"))
    assert first.key != second.key


def test_valid_play_has_no_rejection_reason():
    assert rejection_reason(parse_play(raw())) is None
    assert rejection_reason(parse_play(raw(duration_seconds=None))) is None


def test_rejects_incomplete_or_unsupported_entries():
    assert rejection_reason(parse_play(raw(title=""))) == "sem título"
    assert rejection_reason(parse_play(raw(artists=[]))) == "sem artista"
    assert rejection_reason(parse_play(raw(duration_seconds=30))) == "duração de até 30 segundos"
    assert (
        rejection_reason(parse_play(raw(videoType="MUSIC_VIDEO_TYPE_PODCAST_EPISODE")))
        == "episódio de podcast"
    )
    assert (
        rejection_reason(parse_play(raw(videoType="MUSIC_VIDEO_TYPE_UGC")))
        == "vídeo enviado por usuário"
    )
