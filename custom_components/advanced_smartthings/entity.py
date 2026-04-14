from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AdvancedSmartThingsCoordinator
from .discovery import DiscoveredDevice


class AdvancedSmartThingsEntity(CoordinatorEntity[AdvancedSmartThingsCoordinator]):
    """Base entity for Advanced SmartThings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AdvancedSmartThingsCoordinator,
        device: DiscoveredDevice,
        description: Any,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._device = device
        self._attr_unique_id = f"{device.device_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.device_id)},
            name=self._device.label,
            manufacturer=self._device.manufacturer_name,
            model=self._device.name or self._device.device_type_name,
            model_id=self._device.device_type_name,
            configuration_url="https://api.smartthings.com",
        )

    @property
    def available(self) -> bool:
        return self._device.device_id in self.coordinator.data

    def _capability_payload(
        self,
        *,
        component_id: str | None = None,
        capability: str | None = None,
    ) -> dict[str, Any] | None:
        status = self.coordinator.data.get(self._device.device_id)
        if status is None:
            return None
        components = status.get("components")
        if not isinstance(components, dict):
            return None
        component = components.get(component_id or self.entity_description.component_id)
        if not isinstance(component, dict):
            return None
        capability_payload = component.get(capability or self.entity_description.capability)
        return capability_payload if isinstance(capability_payload, dict) else None

    def _lookup_path(
        self,
        path: Sequence[str],
        *,
        component_id: str | None = None,
        capability: str | None = None,
    ) -> Any:
        payload = self._capability_payload(component_id=component_id, capability=capability)
        if payload is None:
            return None
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    async def _async_send_command(self, command: str, arguments: list[Any] | None = None) -> None:
        await self.coordinator.api.async_send_command(
            self._device.device_id,
            self.entity_description.component_id,
            self.entity_description.capability,
            command,
            arguments,
        )
        await self.coordinator.async_request_refresh()
