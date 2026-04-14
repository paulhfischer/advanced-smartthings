from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def test_translation_files_cover_same_key_structure() -> None:
    integration_dir = (
        Path(__file__).resolve().parent.parent / "custom_components" / "advanced_smartthings"
    )
    strings = json.loads((integration_dir / "strings.json").read_text())
    english = json.loads((integration_dir / "translations" / "en.json").read_text())
    german = json.loads((integration_dir / "translations" / "de.json").read_text())

    string_keys = _flatten_keys(strings)
    english_keys = _flatten_keys(english)
    german_keys = _flatten_keys(german)

    assert english_keys == german_keys
    assert english_keys <= string_keys


def _flatten_keys(payload: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            keys.add(next_prefix)
            keys |= _flatten_keys(value, next_prefix)
    return keys
