import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scrobbler.history import Scrobble, parse_play, rejection_reason
from scrobbler.lastfm import BATCH_SIZE, Ignored, Lastfm, LastfmError, LastfmRejectedError
from scrobbler.selection import estimate_timestamps, select_new
from scrobbler.state import State, load_state, save_state

log = logging.getLogger(__name__)


@dataclass
class Summary:
    found: int = 0
    already_processed: int = 0
    new: int = 0
    skipped: int = 0
    carried_over: int = 0
    accepted: int = 0
    ignored: int = 0
    pending: int = 0


def run_sync(
    fetch_history: Callable[[], list[Any]],
    lastfm: Lastfm,
    state_path: Path,
    now: datetime,
    dry_run: bool,
) -> Summary:
    summary = Summary()
    state = load_state(state_path)
    if state is None:
        log.info(
            "Nenhum estado anterior: primeira execução, somente músicas de hoje serão enviadas."
        )
    else:
        log.info("Última sincronização: %s", state.synced_at.astimezone(now.tzinfo).isoformat())
    log.info("Last.fm autenticado como %s", lastfm.username())

    plays = [play for play in map(parse_play, fetch_history()) if play]
    summary.found = len(plays)
    log.info("%d músicas encontradas no histórico do YouTube Music", len(plays))

    since = state.synced_at if state else None
    selected = select_new(plays, state.history if state else None, since, now)
    summary.new = len(selected)
    summary.already_processed = len(plays) - len(selected)

    valid = []
    for play in selected:
        reason = rejection_reason(play)
        if reason:
            summary.skipped += 1
            log.info("Ignorada (%s): %s — %s", reason, play.artist or "?", play.title or "?")
        else:
            valid.append(play)

    stamps = estimate_timestamps(valid, since, now)
    fresh = [
        Scrobble(play.artist, play.title, stamp, play.album, play.duration)
        for play, stamp in zip(valid, stamps, strict=True)
    ]
    carried = state.pending if state else []
    summary.carried_over = len(carried)
    pending = carried + fresh[::-1]
    summary.pending = len(pending)

    for scrobble in pending:
        log.info(
            "%s %s (horário estimado) %s — %s",
            "Seria enviada:" if dry_run else "Na fila:",
            datetime.fromtimestamp(scrobble.timestamp, now.tzinfo).strftime("%Y-%m-%d %H:%M"),
            scrobble.artist,
            scrobble.title,
        )
    if dry_run:
        return summary

    history = [play.key for play in plays] or (state.history if state else [])
    state = State(history=history, synced_at=now, pending=pending)
    save_state(state_path, state)

    size = BATCH_SIZE
    while state.pending:
        batch = state.pending[:size]
        try:
            ignored = lastfm.scrobble(batch)
        except LastfmRejectedError as error:
            if size > 1:
                log.warning("Lote recusado; reenviando um scrobble por vez: %s", error)
                size = 1
                continue
            ignored = [Ignored(batch[0], "recusado", str(error))]
        except LastfmError as error:
            log.error(
                "Envio interrompido; %d scrobbles ficam pendentes: %s", len(state.pending), error
            )
            break
        state.pending = state.pending[len(batch) :]
        save_state(state_path, state)
        summary.accepted += len(batch) - len(ignored)
        summary.ignored += len(ignored)
        for item in ignored:
            log.warning(
                "Last.fm ignorou (%s): %s — %s",
                item.reason,
                item.scrobble.artist,
                item.scrobble.title,
            )
    summary.pending = len(state.pending)
    return summary


def log_summary(summary: Summary, dry_run: bool) -> None:
    log.info("Resumo%s:", " (dry-run, nada foi enviado nem salvo)" if dry_run else "")
    log.info("  identificadas no histórico: %d", summary.found)
    log.info("  já processadas ou fora da janela: %d", summary.already_processed)
    log.info("  novas: %d", summary.new)
    log.info("  ignoradas localmente: %d", summary.skipped)
    log.info("  pendentes de execuções anteriores: %d", summary.carried_over)
    if dry_run:
        log.info("  seriam enviadas: %d", summary.pending)
        return
    log.info("  aceitas pelo Last.fm: %d", summary.accepted)
    log.info("  ignoradas pelo Last.fm: %d", summary.ignored)
    log.info("  ainda pendentes: %d", summary.pending)
