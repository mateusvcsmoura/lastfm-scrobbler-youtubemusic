import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicError, YTMusicServerError, YTMusicUserError


class YouTubeMusicError(Exception):
    pass


class YouTubeMusicAuthError(YouTubeMusicError):
    pass


def parse_browser_auth(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text.startswith("{"):
        path = Path(text)
        if not path.is_file():
            raise YouTubeMusicAuthError(
                "BROWSER_JSON deve conter o JSON gerado por 'ytmusicapi browser' "
                "ou o caminho de um arquivo existente."
            )
        text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise YouTubeMusicAuthError(
            f"BROWSER_JSON não é um JSON válido (linha {error.lineno}, coluna {error.colno})."
        ) from None
    if not isinstance(data, dict):
        raise YouTubeMusicAuthError(
            "BROWSER_JSON deve ser um objeto JSON com os headers do navegador."
        )

    headers = {str(key).lower(): header for key, header in data.items()}
    cookie = headers.get("cookie")
    authorization = headers.get("authorization")
    if not isinstance(cookie, str) or "__Secure-3PAPISID" not in cookie:
        raise YouTubeMusicAuthError(
            "BROWSER_JSON não contém o cookie __Secure-3PAPISID de uma sessão autenticada."
        )
    if not isinstance(authorization, str) or "SAPISIDHASH" not in authorization:
        raise YouTubeMusicAuthError(
            "BROWSER_JSON não contém o header authorization (SAPISIDHASH) de uma sessão válida."
        )
    return data


def fetch_history(auth: dict[str, Any], now: datetime) -> list[Any]:
    try:
        client = YTMusic(auth=auth, language="en")
        context = client.context["context"]["client"]
        context["timeZone"] = str(now.tzinfo)
        context["utcOffsetMinutes"] = int(now.utcoffset().total_seconds() // 60)
        history = client.get_history()
    except YTMusicUserError as error:
        raise YouTubeMusicAuthError(f"Autenticação do YouTube Music inválida: {error}") from error
    except YTMusicServerError as error:
        if "HTTP 401" in str(error) or "HTTP 403" in str(error):
            raise YouTubeMusicAuthError(
                "YouTube Music recusou a autenticação; os cookies expiraram ou foram revogados. "
                "Gere um novo browser.json."
            ) from error
        raise YouTubeMusicError(f"YouTube Music retornou erro: {error}") from error
    except requests.RequestException as error:
        raise YouTubeMusicError(
            f"Falha de rede ao consultar o YouTube Music ({type(error).__name__})."
        ) from error
    except (YTMusicError, KeyError, IndexError, TypeError) as error:
        raise YouTubeMusicError(
            "Resposta inesperada do YouTube Music ao ler o histórico. A autenticação pode ter "
            "expirado ou a estrutura da página mudou; gere um novo browser.json ou atualize o "
            "ytmusicapi."
        ) from error
    if not isinstance(history, list):
        raise YouTubeMusicError("YouTube Music retornou um histórico em formato inesperado.")
    return history
