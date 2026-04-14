from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import UTC
from pathlib import Path

from app.models import PersistentState
from app.models import TokenBundle
from app.storage import StateStorage


def test_state_storage_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    storage = StateStorage(path)
    state = PersistentState(
        token=TokenBundle(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        ),
        auth_broken=False,
    )

    storage.save(state)
    restored = storage.load()

    assert restored.token is not None
    assert restored.token.access_token == "access-token"
    assert restored.token.refresh_token == "refresh-token"
