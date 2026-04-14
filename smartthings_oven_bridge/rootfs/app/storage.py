from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from pydantic import ValidationError

from .errors import StorageError
from .models import PersistentState


class StateStorage:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> PersistentState:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return PersistentState()

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return PersistentState.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as err:
            raise StorageError(
                message=f"Unable to load state from {self._path}.",
                details={"error": str(err)},
            ) from err

    def save(self, state: PersistentState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True)

        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            temp_path.replace(self._path)
        except OSError as err:
            raise StorageError(
                message=f"Unable to persist state to {self._path}.",
                details={"error": str(err)},
            ) from err
