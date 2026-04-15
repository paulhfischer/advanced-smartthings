from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsButtonEntityDescription,
    coerce_numeric_value,
    format_duration_minutes,
    parse_duration_minutes,
    resolve_standard_oven_start_mode,
)
from .entity import AdvancedSmartThingsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        AdvancedSmartThingsButtonEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsButtonEntityDescription)
    )


class AdvancedSmartThingsButtonEntity(AdvancedSmartThingsEntity, ButtonEntity):
    """SmartThings button entity."""

    entity_description: AdvancedSmartThingsButtonEntityDescription

    async def async_press(self) -> None:
        if self.entity_description.press_strategy == "oven_start_program":
            await self._async_start_oven_program()
            return

        self._require_remote_control_enabled()
        await self._async_send_command(
            self.entity_description.command,
            list(self.entity_description.arguments),
        )

    async def _async_start_oven_program(self) -> None:
        self._require_remote_control_enabled()

        mode = self._current_oven_mode_raw()
        if mode in {None, "NoOperation"}:
            raise HomeAssistantError("Select an oven mode before starting the oven.")

        spec = self._current_oven_mode_spec()
        if not _supports_operation(spec, "start"):
            raise HomeAssistantError("The selected oven mode cannot be started from SmartThings.")

        temperature = self._start_temperature_value(spec)
        standard_start = self._standard_oven_start_target(mode)
        if standard_start is not None:
            component_id, start_mode = standard_start
            await self._async_start_standard_oven_program(
                component_id=component_id,
                mode=mode,
                start_mode=start_mode,
                temperature=temperature,
            )
            return

        await self._async_start_samsung_oven_program(
            component_id=self.entity_description.component_id,
            mode=mode,
            temperature=temperature,
        )

    def _start_temperature_value(self, spec: dict[str, Any] | None) -> int | None:
        current_value = coerce_numeric_value(
            self._lookup_path(
                ("ovenSetpoint", "value"),
                component_id=self.entity_description.component_id,
                capability="ovenSetpoint",
            )
        )
        if current_value is not None and current_value > 0:
            return int(current_value)

        supported_options = spec.get("supportedOptions") if isinstance(spec, dict) else None
        if not isinstance(supported_options, dict):
            return None

        temperature_options = supported_options.get("temperature")
        if not isinstance(temperature_options, dict):
            return None

        raw_unit = self._lookup_path(
            ("ovenSetpoint", "unit"),
            component_id=self.entity_description.component_id,
            capability="ovenSetpoint",
        )
        preferred_unit = raw_unit if raw_unit in {"C", "F"} else "C"

        by_unit = temperature_options.get(preferred_unit)
        if not isinstance(by_unit, dict):
            by_unit = next(
                (option for option in temperature_options.values() if isinstance(option, dict)),
                None,
            )
        if not isinstance(by_unit, dict):
            return None

        default_value = coerce_numeric_value(by_unit.get("default"))
        return int(default_value) if default_value is not None else None

    def _start_operation_time_value(self) -> str | None:
        raw_value = self._lookup_path(
            ("operationTime", "value"),
            component_id=self.entity_description.component_id,
            capability="samsungce.ovenOperatingState",
        )
        parsed_minutes = parse_duration_minutes(raw_value)
        if parsed_minutes is None or parsed_minutes <= 0:
            return None
        return format_duration_minutes(parsed_minutes)

    def _start_operation_time_seconds(self) -> int | None:
        formatted_value = self._start_operation_time_value()
        if formatted_value is not None:
            parsed_minutes = parse_duration_minutes(formatted_value)
            if parsed_minutes is not None:
                return max(0, int(round(parsed_minutes * 60)))

        raw_value = self._lookup_path(
            ("operationTime", "value"),
            component_id=self.entity_description.component_id,
            capability="ovenOperatingState",
        )
        if isinstance(raw_value, int | float):
            return max(0, int(raw_value))
        return None

    def _standard_oven_start_target(self, raw_mode: str) -> tuple[str, str] | None:
        for component_id in self._standard_oven_start_components():
            raw_supported_modes = self._lookup_path(
                ("supportedOvenModes", "value"),
                component_id=component_id,
                capability="ovenMode",
            )
            supported_modes = (
                [value for value in raw_supported_modes if isinstance(value, str)]
                if isinstance(raw_supported_modes, list)
                else []
            )
            if not supported_modes:
                continue

            mapped_mode = resolve_standard_oven_start_mode(raw_mode, supported_modes)
            if mapped_mode is not None:
                return component_id, mapped_mode
        return None

    def _standard_oven_start_components(self) -> list[str]:
        component_ids: list[str] = []
        for preferred_component_id in ("main", self.entity_description.component_id):
            if preferred_component_id in component_ids:
                continue
            if self._device_component_has_capability(preferred_component_id, "ovenOperatingState"):
                component_ids.append(preferred_component_id)
        return component_ids

    def _device_component_has_capability(self, component_id: str, capability_id: str) -> bool:
        for raw_component in self._device.raw.get("components", []):
            if not isinstance(raw_component, dict):
                continue
            if raw_component.get("id") != component_id:
                continue
            for raw_capability in raw_component.get("capabilities", []):
                if isinstance(raw_capability, dict) and raw_capability.get("id") == capability_id:
                    return True
        return False

    async def _async_start_standard_oven_program(
        self,
        *,
        component_id: str,
        mode: str,
        start_mode: str,
        temperature: int | None,
    ) -> None:
        arguments: list[Any] = [start_mode]
        operation_time_seconds = self._start_operation_time_seconds()
        if operation_time_seconds is not None or temperature is not None:
            arguments.append(operation_time_seconds or 0)
        if temperature is not None:
            arguments.append(temperature)

        optimistic_updates = self._start_optimistic_updates(mode, temperature)
        if operation_time_seconds is not None:
            optimistic_updates.extend(
                [
                    (
                        self.entity_description.component_id,
                        "samsungce.ovenOperatingState",
                        ("operationTime", "value"),
                        format_duration_minutes(operation_time_seconds / 60),
                    ),
                    (
                        component_id,
                        "ovenOperatingState",
                        ("operationTime", "value"),
                        operation_time_seconds,
                    ),
                ]
            )

        await self.coordinator.api.async_send_command(
            self._device.device_id,
            component_id,
            "ovenOperatingState",
            "start",
            arguments,
        )
        self._apply_optimistic_updates(optimistic_updates)
        self.coordinator.async_schedule_post_command_refresh()

    async def _async_start_samsung_oven_program(
        self,
        *,
        component_id: str,
        mode: str,
        temperature: int | None,
    ) -> None:
        commands: list[dict[str, Any]] = [
            {
                "component": component_id,
                "capability": "samsungce.ovenMode",
                "command": "setOvenMode",
                "arguments": [mode],
            }
        ]
        optimistic_updates = self._start_optimistic_updates(mode, temperature)

        if temperature is not None:
            commands.append(
                {
                    "component": component_id,
                    "capability": "ovenSetpoint",
                    "command": "setOvenSetpoint",
                    "arguments": [temperature],
                }
            )

        operation_time = self._start_operation_time_value()
        if operation_time is not None:
            commands.append(
                {
                    "component": component_id,
                    "capability": "samsungce.ovenOperatingState",
                    "command": "setOperationTime",
                    "arguments": [operation_time],
                }
            )
            optimistic_updates.append(
                (
                    component_id,
                    "samsungce.ovenOperatingState",
                    ("operationTime", "value"),
                    operation_time,
                )
            )

        commands.append(
            {
                "component": component_id,
                "capability": self.entity_description.capability,
                "command": self.entity_description.command,
                "arguments": [],
            }
        )

        await self._async_send_commands(commands, optimistic_updates=optimistic_updates)

    def _start_optimistic_updates(
        self,
        mode: str,
        temperature: int | None,
    ) -> list[tuple[str, str, Sequence[str], Any]]:
        updates: list[tuple[str, str, Sequence[str], Any]] = [
            (
                self.entity_description.component_id,
                "samsungce.ovenMode",
                ("ovenMode", "value"),
                mode,
            )
        ]
        if temperature is not None:
            updates.append(
                (
                    self.entity_description.component_id,
                    "ovenSetpoint",
                    ("ovenSetpoint", "value"),
                    temperature,
                )
            )
        return updates


def _supports_operation(spec: dict[str, Any] | None, operation: str) -> bool:
    if not isinstance(spec, dict):
        return True
    supported_operations = spec.get("supportedOperations")
    if not isinstance(supported_operations, list):
        return True
    return operation in [value for value in supported_operations if isinstance(value, str)]
