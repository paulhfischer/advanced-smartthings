from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsNumberEntityDescription,
    coerce_numeric_value,
    format_duration_minutes,
    normalize_temperature_unit,
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
        AdvancedSmartThingsNumberEntity(runtime.coordinator, device, description)
        for device in runtime.devices.values()
        for description in device.supported_entities
        if isinstance(description, AdvancedSmartThingsNumberEntityDescription)
    )


class AdvancedSmartThingsNumberEntity(AdvancedSmartThingsEntity, NumberEntity):
    """SmartThings number entity."""

    entity_description: AdvancedSmartThingsNumberEntityDescription

    @property
    def native_value(self) -> float | None:
        raw_value = self._lookup_path(self.entity_description.value_path)
        if self.entity_description.value_kind == "duration_minutes":
            return parse_duration_minutes(raw_value)
        return coerce_numeric_value(raw_value)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.unit_path:
            raw_unit = self._lookup_path(self.entity_description.unit_path)
            normalized = normalize_temperature_unit(raw_unit)
            if normalized is not None:
                return normalized
        return self.entity_description.native_unit_of_measurement

    @property
    def native_min_value(self) -> float | None:
        return self._number_range_value(index=0)

    @property
    def native_max_value(self) -> float | None:
        return self._number_range_value(index=1)

    @property
    def native_step(self) -> float | None:
        return self._number_range_value(index=2)

    async def async_set_native_value(self, value: float) -> None:
        if self.entity_description.value_kind == "duration_minutes":
            await self._async_send_command(
                self.entity_description.command,
                [format_duration_minutes(value)],
            )
            return

        command_value: float | int = int(value) if self.entity_description.cast_to_int else value
        await self._async_send_command(self.entity_description.command, [command_value])

    def _number_range_value(self, *, index: int) -> float | None:
        range_values = self._resolved_range()
        if range_values is not None:
            return range_values[index]

        if index == 0:
            return self.entity_description.static_min_value
        if index == 1:
            return self.entity_description.static_max_value
        return self.entity_description.static_step or self.entity_description.native_step

    def _resolved_range(self) -> tuple[float, float, float] | None:
        strategy = self.entity_description.range_strategy
        if strategy == "status_range":
            raw_range = self._lookup_path(self.entity_description.range_path)
            return _numeric_range_from_status(raw_range)
        if strategy == "oven_temperature_spec":
            spec = self._current_oven_mode_spec()
            return _numeric_range_from_oven_spec(
                spec, "temperature", self.native_unit_of_measurement
            )
        if strategy == "oven_timer_spec":
            spec = self._current_oven_mode_spec()
            return _duration_range_from_oven_spec(spec)
        if self.entity_description.fallback_range is not None:
            minimum, maximum, step, _ = self.entity_description.fallback_range
            return minimum, maximum, step
        return None

    def _current_oven_mode_spec(self) -> dict[str, Any] | None:
        raw_spec = self._lookup_path(
            ("specification", "value", "single"),
            component_id="main",
            capability="samsungce.kitchenModeSpecification",
        )
        if not isinstance(raw_spec, list):
            return None

        by_mode: dict[str, dict[str, Any]] = {}
        for entry in raw_spec:
            if not isinstance(entry, dict):
                continue
            mode = entry.get("mode")
            if isinstance(mode, str) and mode:
                by_mode[mode] = entry

        current_mode = self._lookup_path(
            ("ovenMode", "value"),
            component_id=self.entity_description.component_id,
            capability="samsungce.ovenMode",
        )
        if isinstance(current_mode, str) and current_mode in by_mode:
            return by_mode[current_mode]

        default_mode = self._lookup_path(
            ("defaultOvenMode", "value"),
            component_id="main",
            capability="samsungce.kitchenDeviceDefaults",
        )
        if isinstance(default_mode, str) and default_mode in by_mode:
            return by_mode[default_mode]

        return next(iter(by_mode.values()), None)


def _numeric_range_from_status(raw_range: Any) -> tuple[float, float, float] | None:
    if not isinstance(raw_range, dict):
        return None
    minimum = raw_range.get("minimum")
    maximum = raw_range.get("maximum")
    step = raw_range.get("step", 1)
    if not isinstance(minimum, int | float) or not isinstance(maximum, int | float):
        return None
    parsed_step = float(step) if isinstance(step, int | float) else 1.0
    return float(minimum), float(maximum), parsed_step


def _numeric_range_from_oven_spec(
    spec: dict[str, Any] | None,
    option_name: str,
    unit: str | None,
) -> tuple[float, float, float] | None:
    if not isinstance(spec, dict):
        return None
    supported_options = spec.get("supportedOptions")
    if not isinstance(supported_options, dict):
        return None
    option = supported_options.get(option_name)
    if not isinstance(option, dict):
        return None

    unit_key = "C" if unit == "°C" else "F" if unit == "°F" else "C"
    by_unit = option.get(unit_key)
    if not isinstance(by_unit, dict):
        by_unit = option.get("C")
    if not isinstance(by_unit, dict):
        return None

    minimum = by_unit.get("min")
    maximum = by_unit.get("max")
    resolution = by_unit.get("resolution", 1)
    if not isinstance(minimum, int | float) or not isinstance(maximum, int | float):
        return None
    step = float(resolution) if isinstance(resolution, int | float) else 1.0
    return float(minimum), float(maximum), step


def _duration_range_from_oven_spec(
    spec: dict[str, Any] | None,
) -> tuple[float, float, float] | None:
    if not isinstance(spec, dict):
        return None
    supported_options = spec.get("supportedOptions")
    if not isinstance(supported_options, dict):
        return None
    operation_time = supported_options.get("operationTime")
    if not isinstance(operation_time, dict):
        return None
    minimum = parse_duration_minutes(operation_time.get("min"))
    maximum = parse_duration_minutes(operation_time.get("max"))
    resolution = parse_duration_minutes(operation_time.get("resolution"))
    if minimum is None or maximum is None:
        return None
    return minimum, maximum, resolution or 1.0
