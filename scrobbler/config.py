from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/Sao_Paulo")
DEFAULT_STATE_FILE = Path("state/state.json")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    lastfm_api_key: str
    lastfm_api_secret: str
    lastfm_session_key: str
    browser_json: str


def require(env: Mapping[str, str], *names: str) -> list[str]:
    values = [env.get(name, "").strip() for name in names]
    missing = [name for name, value in zip(names, values, strict=True) if not value]
    if missing:
        raise ConfigError(
            "Variáveis de ambiente obrigatórias ausentes: "
            + ", ".join(missing)
            + ". Preencha o .env (local) ou os secrets do GitHub Actions."
        )
    return values


def load_settings(env: Mapping[str, str]) -> Settings:
    return Settings(
        *require(env, "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "BROWSER_JSON")
    )
