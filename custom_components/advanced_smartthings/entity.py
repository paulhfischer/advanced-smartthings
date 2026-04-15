from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .capability_registry import (
    AdvancedSmartThingsButtonEntityDescription,
    coerce_numeric_value,
    normalize_bool_value,
    normalize_temperature_unit,
    parse_duration_minutes,
)
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
        if object_id_suffix := getattr(description, "object_id_suffix", None):
            self._attr_suggested_object_id = f"{slugify(device.label)}_{object_id_suffix}"

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
        if self._device.device_id not in self.coordinator.data:
            return False
        if getattr(self.entity_description, "requires_remote_control", False):
            return self._remote_control_enabled() is not False
        return True

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

    def _actual_oven_mode_raw(self) -> str | None:
        mode_source = self._actual_oven_mode_source()
        if mode_source is None:
            return None
        return mode_source[2]

    def _preferred_oven_input_mode_raw(self) -> str | None:
        current_mode = self._current_oven_mode_raw()
        if current_mode not in {None, "NoOperation"}:
            return current_mode

        default_mode = self._lookup_path(
            ("defaultOvenMode", "value"),
            component_id="main",
            capability="samsungce.kitchenDeviceDefaults",
        )
        if isinstance(default_mode, str) and default_mode and default_mode != "NoOperation":
            return default_mode

        current_spec = self._current_oven_mode_spec()
        if isinstance(current_spec, dict):
            mode = current_spec.get("mode")
            if isinstance(mode, str) and mode and mode != "NoOperation":
                return mode
        return None

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

    def _oven_mode_spec_for(self, raw_mode: str | None) -> dict[str, Any] | None:
        if raw_mode is None:
            return None
        for entry in self._iter_oven_mode_specs():
            if entry.get("mode") == raw_mode:
                return entry
        return None

    def _current_oven_mode_spec(self) -> dict[str, Any] | None:
        by_mode = {
            entry["mode"]: entry
            for entry in self._iter_oven_mode_specs()
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

    def _oven_is_running(self) -> bool | None:
        seen_inactive = False
        for component_id in self._oven_component_ids():
            samsung_state = normalize_bool_value(
                self._lookup_path(
                    ("operatingState", "value"),
                    component_id=component_id,
                    capability="samsungce.ovenOperatingState",
                )
            )
            if samsung_state is True:
                return True
            if samsung_state is False:
                seen_inactive = True

            standard_state = normalize_bool_value(
                self._lookup_path(
                    ("machineState", "value"),
                    component_id=component_id,
                    capability="ovenOperatingState",
                )
            )
            if standard_state is True:
                return True
            if standard_state is False:
                seen_inactive = True

        return False if seen_inactive else None

    def _oven_component_ids(self) -> list[str]:
        component_ids: list[str] = []
        for component_id in (self.entity_description.component_id, "main"):
            if component_id not in component_ids:
                component_ids.append(component_id)
        for raw_component in self._device.raw.get("components", []):
            if not isinstance(raw_component, dict):
                continue
            component_id = raw_component.get("id")
            if isinstance(component_id, str) and component_id not in component_ids:
                component_ids.append(component_id)
        return component_ids

    def _oven_mode_candidates(self) -> list[str]:
        return [candidate[2] for candidate in self._oven_mode_candidates_with_sources()]

    def _actual_oven_mode_source(self) -> tuple[str, str, str] | None:
        candidates = self._oven_mode_candidates_with_sources()
        if not candidates:
            return None

        running = self._oven_is_running()
        if running is True:
            for candidate in candidates:
                if candidate[2] not in {"NoOperation", "Others"}:
                    return candidate

        for candidate in candidates:
            if candidate[2] != "Others":
                return candidate
        return candidates[0]

    def _oven_mode_candidates_with_sources(self) -> list[tuple[str, str, str]]:
        candidates: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for component_id in self._oven_component_ids():
            for capability in ("samsungce.ovenMode", "ovenMode"):
                raw_mode = self._lookup_path(
                    ("ovenMode", "value"),
                    component_id=component_id,
                    capability=capability,
                )
                if not isinstance(raw_mode, str) or not raw_mode:
                    continue
                key = (component_id, capability, raw_mode)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(key)
        return candidates

    def _actual_oven_setpoint_value(self) -> float | None:
        candidates = self._oven_setpoint_candidates()
        if not candidates:
            return None

        running = self._oven_is_running()
        if running is True:
            for _, value, _ in candidates:
                if value is not None and value > 0:
                    return value

        for _, value, _ in candidates:
            if value is not None:
                return value
        return None

    def _actual_oven_setpoint_unit(self) -> str | None:
        candidates = self._oven_setpoint_candidates()
        if not candidates:
            return None

        running = self._oven_is_running()
        if running is True:
            for _, value, unit in candidates:
                if value is not None and value > 0 and unit is not None:
                    return unit

        for _, _, unit in candidates:
            if unit is not None:
                return unit
        return None

    def _actual_oven_timer_minutes(self) -> float | None:
        candidates = self._oven_timer_candidates()
        if not candidates:
            return None

        running = self._oven_is_running()
        if running is True:
            for _, minutes in candidates:
                if minutes is not None and minutes > 0:
                    return minutes

        for _, minutes in candidates:
            if minutes is not None:
                return minutes
        return None

    def _oven_state_component_ids(self) -> list[str]:
        ordered: list[str] = []
        active_mode_source = self._actual_oven_mode_source()
        if active_mode_source is not None:
            ordered.append(active_mode_source[0])
        for component_id in self._oven_component_ids():
            if component_id not in ordered:
                ordered.append(component_id)
        return ordered

    def _oven_setpoint_candidates(self) -> list[tuple[str, float | None, str | None]]:
        candidates: list[tuple[str, float | None, str | None]] = []
        seen_components: set[str] = set()
        for component_id in self._oven_state_component_ids():
            if component_id in seen_components:
                continue
            seen_components.add(component_id)
            value = coerce_numeric_value(
                self._lookup_path(
                    ("ovenSetpoint", "value"),
                    component_id=component_id,
                    capability="ovenSetpoint",
                )
            )
            raw_unit = self._lookup_path(
                ("ovenSetpoint", "unit"),
                component_id=component_id,
                capability="ovenSetpoint",
            )
            unit = normalize_temperature_unit(raw_unit)
            if value is None and unit is None:
                continue
            candidates.append((component_id, value, unit))
        return candidates

    def _oven_timer_candidates(self) -> list[tuple[str, float | None]]:
        candidates: list[tuple[str, float | None]] = []
        seen: set[tuple[str, str]] = set()
        for component_id in self._oven_state_component_ids():
            for capability in ("samsungce.ovenOperatingState", "ovenOperatingState"):
                key = (component_id, capability)
                if key in seen:
                    continue
                seen.add(key)
                minutes = parse_duration_minutes(
                    self._lookup_path(
                        ("operationTime", "value"),
                        component_id=component_id,
                        capability=capability,
                    )
                )
                if minutes is None:
                    continue
                candidates.append((component_id, minutes))
        return candidates

    def _oven_control_helper(self):
        from .button import AdvancedSmartThingsButtonEntity

        description = AdvancedSmartThingsButtonEntityDescription(
            key=f"{self.entity_description.key}_helper",
            name="Oven control helper",
            device_id=self._device.device_id,
            device_label=self._device.label,
            component_id=self.entity_description.component_id,
            component_label=self.entity_description.component_label,
            capability="samsungce.ovenOperatingState",
            requires_remote_control=True,
            command="start",
            press_strategy="oven_start_program",
        )
        return AdvancedSmartThingsButtonEntity(self.coordinator, self._device, description)

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
