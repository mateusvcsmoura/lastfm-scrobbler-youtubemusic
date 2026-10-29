import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from scrobbler.history import Scrobble

STATE_VERSION = 1


class StateError(Exception):
    pass


@dataclass
class State:
    history: list[str]
    synced_at: datetime
    pending: list[Scrobble] = field(default_factory=list)


def load_state(path: Path) -> State | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != STATE_VERSION:
            raise StateError(f"Versão de estado não suportada em {path}: {data['version']}")
        if not isinstance(data["history"], list) or not isinstance(data["pending"], list):
            raise TypeError("history e pending devem ser listas")
        return State(
            history=[str(key) for key in data["history"]],
            synced_at=datetime.fromisoformat(data["synced_at"]),
            pending=[Scrobble(**item) for item in data["pending"]],
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StateError(f"Arquivo de estado inválido em {path}: {error}") from error


def save_state(path: Path, state: State) -> None:
    payload = {
        "version": STATE_VERSION,
        "synced_at": state.synced_at.isoformat(),
        "history": state.history,
        "pending": [asdict(scrobble) for scrobble in state.pending],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
