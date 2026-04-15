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
            raise HomeAssistantError(
                "The selected oven mode cannot be started from SmartThings."
            )

        component_id = self.entity_description.component_id
        commands: list[dict[str, Any]] = [
            {
                "component": component_id,
                "capability": "samsungce.ovenMode",
                "command": "setOvenMode",
                "arguments": [mode],
            }
        ]
        optimistic_updates: list[tuple[str, str, Sequence[str], Any]] = [
            (component_id, "samsungce.ovenMode", ("ovenMode", "value"), mode)
        ]

        temperature = self._start_temperature_value(spec)
        if temperature is not None:
            commands.append(
                {
                    "component": component_id,
                    "capability": "ovenSetpoint",
                    "command": "setOvenSetpoint",
                    "arguments": [temperature],
                }
            )
            optimistic_updates.append(
                (component_id, "ovenSetpoint", ("ovenSetpoint", "value"), temperature)
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
                (
                    option
                    for option in temperature_options.values()
                    if isinstance(option, dict)
                ),
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


def _supports_operation(spec: dict[str, Any] | None, operation: str) -> bool:
    if not isinstance(spec, dict):
        return True
    supported_operations = spec.get("supportedOperations")
    if not isinstance(supported_operations, list):
        return True
    return operation in [value for value in supported_operations if isinstance(value, str)]
