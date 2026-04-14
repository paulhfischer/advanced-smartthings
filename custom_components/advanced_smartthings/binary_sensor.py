from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsBinarySensorEntityDescription,
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
        AdvancedSmartThingsBinarySensorEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsBinarySensorEntityDescription)
    )


class AdvancedSmartThingsBinarySensorEntity(AdvancedSmartThingsEntity, BinarySensorEntity):
    """SmartThings binary sensor entity."""

    entity_description: AdvancedSmartThingsBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        raw_value = self._lookup_path(self.entity_description.value_path)
        bool_value = normalize_bool_value(raw_value)
        if bool_value is not None:
            return bool_value

        normalized = normalize_string_value(raw_value)
        if normalized is None:
            return None
        if normalized in self.entity_description.on_values:
            return True
        if normalized in self.entity_description.off_values:
            return False
        return None
