import logging

import pytest

from scrobbler import __main__ as cli
from scrobbler.config import ConfigError, load_settings

VARIABLES = ("LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "BROWSER_JSON")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli.truststore, "inject_into_ssl", lambda: None)
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_settings_require_every_credential():
    with pytest.raises(ConfigError) as error:
        load_settings({"LASTFM_API_KEY": "chave-real", "LASTFM_SESSION_KEY": "   "})
    assert "LASTFM_API_SECRET, LASTFM_SESSION_KEY, BROWSER_JSON" in str(error.value)
    assert "chave-real" not in str(error.value)


def test_settings_are_loaded_from_environment():
    settings = load_settings(dict.fromkeys(VARIABLES, " valor "))
    assert settings.lastfm_session_key == "valor"


def test_missing_credentials_exit_with_failure(caplog, tmp_path):
    with caplog.at_level(logging.ERROR):
        assert cli.main(["--state-file", str(tmp_path / "state.json")]) == 1
    assert "Variáveis de ambiente obrigatórias ausentes" in caplog.text
    assert not (tmp_path / "state.json").exists()


def test_invalid_youtube_auth_fails_without_leaking_secret(caplog, monkeypatch, tmp_path):
    for name in VARIABLES:
        monkeypatch.setenv(name, "segredo-super-secreto")
    with caplog.at_level(logging.INFO):
        assert cli.main(["--dry-run", "--state-file", str(tmp_path / "state.json")]) == 1
    assert "BROWSER_JSON" in caplog.text
    assert "segredo-super-secreto" not in caplog.text
