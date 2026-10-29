import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import truststore
from dotenv import load_dotenv

from scrobbler.config import DEFAULT_STATE_FILE, TIMEZONE, ConfigError, load_settings, require
from scrobbler.lastfm import LastfmError, connect, create_session_key
from scrobbler.state import StateError
from scrobbler.sync import log_summary, run_sync
from scrobbler.ytmusic import YouTubeMusicError, fetch_history, parse_browser_auth

log = logging.getLogger("scrobbler")


def _sync(state_file: Path, dry_run: bool) -> int:
    settings = load_settings(os.environ)
    auth = parse_browser_auth(settings.browser_json)
    lastfm = connect(
        settings.lastfm_api_key, settings.lastfm_api_secret, settings.lastfm_session_key
    )
    now = datetime.now(TIMEZONE)
    summary = run_sync(lambda: fetch_history(auth, now), lastfm, state_file, now, dry_run)
    log_summary(summary, dry_run)
    return 0 if dry_run or summary.pending == 0 else 1


def _authorize(url: str) -> None:
    print("Abra o link abaixo, autorize o aplicativo no Last.fm e pressione Enter:")
    print(url)
    input()


def _login_lastfm() -> int:
    api_key, api_secret = require(os.environ, "LASTFM_API_KEY", "LASTFM_API_SECRET")
    session_key, username = create_session_key(api_key, api_secret, _authorize)
    print(f"Session key gerada para o usuário {username}:")
    print(session_key)
    print("Salve esse valor em LASTFM_SESSION_KEY no .env e nos secrets do GitHub.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scrobbler",
        description="Sincroniza o histórico do YouTube Music com o Last.fm.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra o que seria enviado sem enviar scrobbles nem alterar o estado",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"arquivo de estado da sincronização (padrão: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--login-lastfm",
        action="store_true",
        help="gera uma LASTFM_SESSION_KEY autorizando o aplicativo pelo navegador",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("pylast").setLevel(logging.WARNING)
    truststore.inject_into_ssl()
    load_dotenv()

    try:
        if args.login_lastfm:
            return _login_lastfm()
        return _sync(args.state_file, args.dry_run)
    except (ConfigError, StateError, YouTubeMusicError, LastfmError) as error:
        log.error("%s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
