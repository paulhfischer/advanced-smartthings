from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsSensorEntityDescription,
    coerce_numeric_value,
    normalize_oven_mode,
    normalize_temperature_unit,
    oven_mode_display_language,
    parse_duration_minutes,
)
from .entity import AdvancedSmartThingsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        AdvancedSmartThingsSensorEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsSensorEntityDescription)
    )


class AdvancedSmartThingsSensorEntity(AdvancedSmartThingsEntity, SensorEntity):
    """SmartThings read-only sensor."""

    entity_description: AdvancedSmartThingsSensorEntityDescription

    @property
    def native_value(self) -> Any:
        raw_value = self._lookup_path(self.entity_description.value_path)
        if self.entity_description.translation_key == "oven_program":
            return normalize_oven_mode(
                self._actual_oven_mode_raw(),
                oven_mode_display_language(self.hass.config.language),
            )
        if self.entity_description.state_kind == "duration_minutes":
            return parse_duration_minutes(raw_value)
        if self.entity_description.state_kind == "numeric":
            numeric = coerce_numeric_value(raw_value)
            if numeric is None:
                return None
            return int(numeric) if numeric.is_integer() else numeric
        return raw_value

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.unit_path:
            raw_unit = self._lookup_path(self.entity_description.unit_path)
            normalized = normalize_temperature_unit(raw_unit)
            if normalized is not None:
                return normalized
        return self.entity_description.native_unit_of_measurement
