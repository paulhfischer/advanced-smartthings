from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .capability_registry import normalize_bool_value
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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not getattr(self.entity_description, "requires_remote_control", False):
            return None
        remote_control_enabled = self._remote_control_enabled()
        if remote_control_enabled is None:
            return None
        return {"remote_control_enabled": remote_control_enabled}

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

    async def _async_send_command(
        self,
        command: str,
        arguments: list[Any] | None = None,
        *,
        component_id: str | None = None,
        capability: str | None = None,
        optimistic_updates: Sequence[tuple[str, str, Sequence[str], Any]] = (),
    ) -> dict[str, Any]:
        payload = await self.coordinator.api.async_send_command(
            self._device.device_id,
            component_id or self.entity_description.component_id,
            capability or self.entity_description.capability,
            command,
            arguments,
        )
        if optimistic_updates:
            self._apply_optimistic_updates(optimistic_updates)
        self.coordinator.async_schedule_post_command_refresh()
        return payload

    async def _async_send_commands(
        self,
        commands: Sequence[dict[str, Any]],
        *,
        optimistic_updates: Sequence[tuple[str, str, Sequence[str], Any]] = (),
    ) -> dict[str, Any]:
        payload = await self.coordinator.api.async_send_commands(
            self._device.device_id,
            list(commands),
        )
        if optimistic_updates:
            self._apply_optimistic_updates(optimistic_updates)
        self.coordinator.async_schedule_post_command_refresh()
        return payload

    async def _async_refresh_device_status(self) -> dict[str, Any]:
        """Refresh the current device status immediately and update coordinator state."""
        status = await self.coordinator.api.async_get_device_status(self._device.device_id)
        updated_data = deepcopy(self.coordinator.data)
        updated_data[self._device.device_id] = status
        self.coordinator.async_set_updated_data(updated_data)
        return status

    def _remote_control_enabled(self) -> bool | None:
        raw_value = self._lookup_path(
            ("remoteControlEnabled", "value"),
            component_id="main",
            capability="remoteControlStatus",
        )
        return normalize_bool_value(raw_value)

    def _require_remote_control_enabled(self) -> None:
        if not getattr(self.entity_description, "requires_remote_control", False):
            return
        if self._remote_control_enabled() is False:
            raise HomeAssistantError("Remote control is disabled for this oven.")

    def _current_oven_mode_raw(self) -> str | None:
        raw_mode = self._lookup_path(
            ("ovenMode", "value"),
            component_id=self.entity_description.component_id,
            capability="samsungce.ovenMode",
        )
        return raw_mode if isinstance(raw_mode, str) and raw_mode else None

    def _iter_oven_mode_specs(self) -> list[dict[str, Any]]:
        raw_spec = self._lookup_path(
            ("specification", "value"),
            component_id="main",
            capability="samsungce.kitchenModeSpecification",
        )
        if not isinstance(raw_spec, dict):
            return []

        specs: list[dict[str, Any]] = []
        for entries in raw_spec.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                mode = entry.get("mode")
                if isinstance(mode, str) and mode:
                    specs.append(entry)
        return specs

    def _current_oven_mode_spec(self) -> dict[str, Any] | None:
        specs = self._iter_oven_mode_specs()
        by_mode = {
            entry["mode"]: entry
            for entry in specs
            if isinstance(entry.get("mode"), str) and entry["mode"]
        }

        current_mode = self._current_oven_mode_raw()
        if current_mode is not None and current_mode in by_mode:
            return by_mode[current_mode]

        default_mode = self._lookup_path(
            ("defaultOvenMode", "value"),
            component_id="main",
            capability="samsungce.kitchenDeviceDefaults",
        )
        if isinstance(default_mode, str) and default_mode in by_mode:
            return by_mode[default_mode]

        return next(iter(by_mode.values()), None)

    def _apply_optimistic_updates(
        self,
        updates: Sequence[tuple[str, str, Sequence[str], Any]],
    ) -> None:
        if self._device.device_id not in self.coordinator.data:
            return

        updated_data = deepcopy(self.coordinator.data)
        device_status = updated_data.get(self._device.device_id)
        if not isinstance(device_status, dict):
            return

        for component_id, capability, path, value in updates:
            components = device_status.setdefault("components", {})
            if not isinstance(components, dict):
                continue
            component = components.setdefault(component_id, {})
            if not isinstance(component, dict):
                continue
            capability_payload = component.setdefault(capability, {})
            if not isinstance(capability_payload, dict):
                continue

            current: Any = capability_payload
            for key in path[:-1]:
                next_value = current.get(key)
                if not isinstance(next_value, dict):
                    next_value = {}
                    current[key] = next_value
                current = next_value
            current[path[-1]] = value

        self.coordinator.async_set_updated_data(updated_data)
