from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capability_registry import AdvancedSmartThingsEntityDescription, build_entity_descriptions
from .models import CapabilityRef, DeviceRecord


@dataclass(slots=True)
class DiscoveredDevice:
    device_id: str
    label: str
    name: str | None
    manufacturer_name: str | None
    device_type_name: str | None
    location_id: str | None
    room_id: str | None
    supported_entities: tuple[AdvancedSmartThingsEntityDescription, ...]
    supported_capabilities: tuple[str, ...]
    unsupported_capabilities: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False)

    @property
    def selectable(self) -> bool:
        return bool(self.supported_entities)

    @property
    def selection_label(self) -> str:
        base = self.label
        if self.name and self.name != self.label:
            base = f"{self.label} ({self.name})"
        return base


def parse_devices(payload: list[dict[str, Any]]) -> list[DeviceRecord]:
    """Normalize the SmartThings device list response."""
    parsed: list[DeviceRecord] = []
    for raw_device in payload:
        device_id = _string_field(raw_device, "deviceId")
        if device_id is None:
            continue

        capabilities: list[CapabilityRef] = []
        for raw_component in raw_device.get("components", []):
            if not isinstance(raw_component, dict):
                continue
            component_id = _string_field(raw_component, "id") or "main"
            component_label = _string_field(raw_component, "label")
            for raw_capability in raw_component.get("capabilities", []):
                if isinstance(raw_capability, str):
                    capabilities.append(
                        CapabilityRef(
                            component_id=component_id,
                            component_label=component_label,
                            capability_id=raw_capability,
                            capability_version=1,
                        )
                    )
                    continue
                if not isinstance(raw_capability, dict):
                    continue
                capability_id = _string_field(raw_capability, "id")
                if capability_id is None:
                    continue
                raw_version = raw_capability.get("version", 1)
                version = raw_version if isinstance(raw_version, int) else 1
                capabilities.append(
                    CapabilityRef(
                        component_id=component_id,
                        component_label=component_label,
                        capability_id=capability_id,
                        capability_version=version,
                    )
                )

        parsed.append(
            DeviceRecord(
                device_id=device_id,
                label=_string_field(raw_device, "label") or device_id,
                name=_string_field(raw_device, "name"),
                manufacturer_name=_string_field(raw_device, "manufacturerName"),
                device_type_name=_string_field(raw_device, "type"),
                location_id=_string_field(raw_device, "locationId"),
                room_id=_string_field(raw_device, "roomId"),
                capabilities=tuple(capabilities),
                raw=raw_device,
            )
        )

    return parsed


def build_device_catalog(
    devices: list[DeviceRecord],
    capability_definitions: dict[tuple[str, int], dict[str, Any] | None],
) -> dict[str, DiscoveredDevice]:
    """Build the supported entity catalog for the selected SmartThings devices."""
    catalog: dict[str, DiscoveredDevice] = {}
    for device in devices:
        supported_entities = build_entity_descriptions(device, capability_definitions)
        supported_capabilities = sorted({entity.capability for entity in supported_entities})
        unsupported_capabilities = sorted(
            capability.capability_id
            for capability in device.capabilities
            if capability.capability_id not in supported_capabilities
        )
        catalog[device.device_id] = DiscoveredDevice(
            device_id=device.device_id,
            label=device.label,
            name=device.name,
            manufacturer_name=device.manufacturer_name,
            device_type_name=device.device_type_name,
            location_id=device.location_id,
            room_id=device.room_id,
            supported_entities=tuple(supported_entities),
            supported_capabilities=tuple(supported_capabilities),
            unsupported_capabilities=tuple(unsupported_capabilities),
            raw=device.raw,
        )
    return catalog


def build_device_options(catalog: dict[str, DiscoveredDevice]) -> dict[str, str]:
    """Return the config flow / options flow selection labels."""
    selectable = [device for device in catalog.values() if device.selectable]
    selectable.sort(key=lambda device: device.selection_label.casefold())
    return {device.device_id: device.selection_label for device in selectable}


def _string_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None
