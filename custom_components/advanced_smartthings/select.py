from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsSelectEntityDescription,
    denormalize_oven_mode,
    normalize_oven_mode,
)
from .entity import AdvancedSmartThingsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        AdvancedSmartThingsSelectEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsSelectEntityDescription)
    )


class AdvancedSmartThingsSelectEntity(AdvancedSmartThingsEntity, SelectEntity):
    """SmartThings select entity."""

    entity_description: AdvancedSmartThingsSelectEntityDescription

    @property
    def current_option(self) -> str | None:
        raw_value = self._lookup_path(self.entity_description.value_path)
        if not isinstance(raw_value, str):
            return None
        if self.entity_description.translation_key == "oven_mode":
            return normalize_oven_mode(raw_value)
        return raw_value

    @property
    def options(self) -> list[str]:
        raw_options = self._lookup_path(self.entity_description.options_path)
        options = (
            [value for value in raw_options if isinstance(value, str)]
            if isinstance(raw_options, list)
            else []
        )
        current_raw = self._lookup_path(self.entity_description.value_path)
        if isinstance(current_raw, str) and current_raw not in options:
            options.append(current_raw)
        if not options:
            options = list(self.entity_description.fallback_options)
        if self.entity_description.translation_key == "oven_mode":
            mapped_options: list[str] = []
            for option in options:
                display = normalize_oven_mode(option)
                if display is not None and display not in mapped_options:
                    mapped_options.append(display)
            return mapped_options
        return options

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported option {option!r} for {self.entity_id}")
        if self.entity_description.translation_key == "oven_mode":
            option = denormalize_oven_mode(option)
        await self._async_send_command(self.entity_description.command, [option])
