from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityRef:
    component_id: str
    component_label: str | None
    capability_id: str
    capability_version: int


@dataclass(slots=True)
class DeviceRecord:
    device_id: str
    label: str
    name: str | None
    manufacturer_name: str | None
    device_type_name: str | None
    location_id: str | None
    room_id: str | None
    capabilities: tuple[CapabilityRef, ...]
    raw: dict[str, Any]
