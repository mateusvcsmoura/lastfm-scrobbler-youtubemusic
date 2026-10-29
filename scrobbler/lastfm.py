import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from xml.dom.minidom import Document

import pylast

from scrobbler.history import Scrobble

BATCH_SIZE = 50
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 10
RETRYABLE_STATUS = {"8", "11", "16", "29", "500", "502", "503", "504"}
AUTH_STATUS = {"4", "9", "10", "13", "14", "15", "26"}
IGNORED_REASONS = {
    "1": "artista filtrado pelo Last.fm",
    "2": "faixa filtrada pelo Last.fm",
    "3": "horário muito antigo",
    "4": "horário no futuro",
    "5": "limite diário de scrobbles excedido",
}

log = logging.getLogger(__name__)


class LastfmError(Exception):
    pass


class LastfmAuthError(LastfmError):
    pass


class LastfmRejectedError(LastfmError):
    pass


@dataclass(frozen=True)
class Ignored:
    scrobble: Scrobble
    code: str
    reason: str


class Lastfm:
    def __init__(
        self, network: pylast.LastFMNetwork, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._network = network
        self._sleep = sleep

    def username(self) -> str:
        return self._call(lambda: self._network.get_authenticated_user().get_name())

    def scrobble(self, batch: list[Scrobble]) -> list[Ignored]:
        if not 0 < len(batch) <= BATCH_SIZE:
            raise ValueError(f"Lote deve ter entre 1 e {BATCH_SIZE} scrobbles")
        params = _scrobble_params(batch)
        document = self._call(
            lambda: pylast._Request(self._network, "track.scrobble", params).execute()
        )
        return _ignored(document, batch)

    def _call[T](self, request: Callable[[], T]) -> T:
        for attempt in count(1):
            try:
                return request()
            except pylast.WSError as error:
                status = str(error.status)
                if status in AUTH_STATUS:
                    raise LastfmAuthError(
                        f"Last.fm recusou as credenciais (código {status}: {error.details}). "
                        "Verifique LASTFM_API_KEY, LASTFM_API_SECRET e LASTFM_SESSION_KEY."
                    ) from error
                if status not in RETRYABLE_STATUS:
                    raise LastfmRejectedError(
                        f"Last.fm recusou a requisição (código {status}: {error.details})"
                    ) from error
                if attempt == MAX_ATTEMPTS:
                    raise LastfmError(f"Last.fm retornou erro {status}: {error.details}") from error
                failure = f"erro {status}"
            except (pylast.NetworkError, pylast.MalformedResponseError) as error:
                if attempt == MAX_ATTEMPTS:
                    raise LastfmError(f"Falha de comunicação com o Last.fm: {error}") from error
                failure = type(error).__name__
            delay = RETRY_DELAY_SECONDS * 2 ** (attempt - 1)
            log.warning(
                "Tentativa %d/%d no Last.fm falhou (%s); repetindo em %ds",
                attempt,
                MAX_ATTEMPTS,
                failure,
                delay,
            )
            self._sleep(delay)


def _scrobble_params(batch: list[Scrobble]) -> dict[str, str | int]:
    params: dict[str, str | int] = {}
    for index, scrobble in enumerate(batch):
        params[f"artist[{index}]"] = scrobble.artist
        params[f"track[{index}]"] = scrobble.title
        params[f"timestamp[{index}]"] = scrobble.timestamp
        if scrobble.album:
            params[f"album[{index}]"] = scrobble.album
        if scrobble.duration:
            params[f"duration[{index}]"] = scrobble.duration
    return params


def _ignored(document: Document, batch: list[Scrobble]) -> list[Ignored]:
    results = document.getElementsByTagName("scrobble")
    if len(results) != len(batch):
        log.warning(
            "Resposta do Last.fm sem detalhes por scrobble (%d de %d); lote considerado enviado",
            len(results),
            len(batch),
        )
    ignored = []
    for scrobble, result in zip(batch, results, strict=False):
        messages = result.getElementsByTagName("ignoredMessage")
        code = messages[0].getAttribute("code") if messages else "0"
        if code != "0":
            ignored.append(
                Ignored(scrobble, code, IGNORED_REASONS.get(code, "motivo desconhecido"))
            )
    return ignored


def connect(api_key: str, api_secret: str, session_key: str) -> Lastfm:
    return Lastfm(
        pylast.LastFMNetwork(api_key=api_key, api_secret=api_secret, session_key=session_key)
    )


def create_session_key(
    api_key: str, api_secret: str, authorize: Callable[[str], None]
) -> tuple[str, str]:
    network = pylast.LastFMNetwork(api_key=api_key, api_secret=api_secret)
    generator = pylast.SessionKeyGenerator(network)
    try:
        url = generator.get_web_auth_url()
        authorize(url)
        return generator.get_web_auth_session_key_username(url)
    except pylast.PyLastError as error:
        raise LastfmAuthError(
            f"Não foi possível gerar a session key do Last.fm: {error}"
        ) from error
