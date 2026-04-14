from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsSwitchEntityDescription,
    normalize_bool_value,
    normalize_string_value,
)
from .entity import AdvancedSmartThingsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        AdvancedSmartThingsSwitchEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsSwitchEntityDescription)
    )


class AdvancedSmartThingsSwitchEntity(AdvancedSmartThingsEntity, SwitchEntity):
    """SmartThings switch entity."""

    entity_description: AdvancedSmartThingsSwitchEntityDescription

    @property
    def is_on(self) -> bool | None:
        raw_value = self._lookup_path(self.entity_description.state_path)
        bool_value = normalize_bool_value(raw_value)
        if bool_value is not None:
            return bool_value

        if isinstance(raw_value, int | float):
            return raw_value > 0

        normalized = normalize_string_value(raw_value)
        if normalized is None:
            return None
        if normalized == "on":
            return True
        if normalized not in {"off", "false"}:
            return True
        if normalized == "off":
            return False
        return None

    async def async_turn_on(self, **kwargs) -> None:
        del kwargs
        await self._async_send_command(
            self.entity_description.on_command,
            self._on_arguments(),
        )

    async def async_turn_off(self, **kwargs) -> None:
        del kwargs
        await self._async_send_command(
            self.entity_description.off_command,
            list(self.entity_description.off_arguments) or None,
        )

    def _on_arguments(self) -> list[Any] | None:
        if not self.entity_description.use_supported_non_off_value:
            return list(self.entity_description.on_arguments) or None

        supported_values = self._lookup_path(self.entity_description.supported_values_path)
        if not isinstance(supported_values, list):
            return ["on"]

        preferred_strings = ("high", "on", "mid", "low", "extraHigh")
        normalized_values = [
            value for value in supported_values if isinstance(value, str) and value != "off"
        ]
        for preferred in preferred_strings:
            if preferred in normalized_values:
                return [preferred]

        for value in supported_values:
            if isinstance(value, int | float) and value > 0:
                return [value]
            if isinstance(value, str) and value != "off":
                return [value]

        return ["on"]
