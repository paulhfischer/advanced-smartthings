from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability_registry import (
    AdvancedSmartThingsSelectEntityDescription,
    coerce_numeric_value,
    denormalize_oven_mode,
    format_duration_minutes,
    normalize_oven_mode,
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
        if self.entity_description.translation_key == "oven_mode":
            if isinstance(raw_value, str) and (
                not self.entity_description.allowed_raw_options
                or raw_value in self.entity_description.allowed_raw_options
            ):
                return normalize_oven_mode(raw_value, self._oven_mode_language())
            preferred_raw = self._preferred_oven_input_mode_raw()
            if preferred_raw is None:
                return None
            return normalize_oven_mode(preferred_raw, self._oven_mode_language())
        if not isinstance(raw_value, str):
            return None
        return raw_value

    @property
    def options(self) -> list[str]:
        if self.entity_description.translation_key == "oven_mode":
            options = self._raw_oven_options()
            mapped_options: list[str] = []
            language = self._oven_mode_language()
            for option in options:
                display = normalize_oven_mode(option, language)
                if display is not None and display not in mapped_options:
                    mapped_options.append(display)
            return mapped_options
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
        return options

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported option {option!r} for {self.entity_id}")
        self._require_remote_control_enabled()
        if self.entity_description.translation_key == "oven_mode":
            raw_option = self._resolve_oven_mode_raw_option(option)
            if raw_option is None:
                raise ValueError(f"Unsupported oven mode {option!r} for {self.entity_id}")
            was_running = self._oven_is_running() is True
            current_raw = self._current_oven_mode_raw()
            helper = self._oven_control_helper()

            if raw_option == "NoOperation":
                if was_running:
                    await helper._async_stop_oven_program()
                if current_raw == raw_option:
                    return
                target = self._resolve_oven_mode_target(raw_option)
                if target is None:
                    raise ValueError(f"Unsupported oven mode {option!r} for {self.entity_id}")
                component_id, capability, command_option = target
                optimistic_updates = self._mode_optimistic_updates(
                    component_id=component_id,
                    capability=capability,
                    raw_option=command_option,
                )
                await self._async_send_command(
                    self.entity_description.command,
                    [command_option],
                    component_id=component_id,
                    capability=capability,
                    optimistic_updates=optimistic_updates,
                )
                return

            target = helper._resolve_oven_control_target(raw_option)
            if was_running and current_raw != raw_option:
                await helper._async_stop_oven_program()

            optimistic_updates = self._mode_optimistic_updates(
                component_id=target.component_id,
                capability=target.mode_capability,
                raw_option=target.mode_value,
            )
            await self._async_send_command(
                self.entity_description.command,
                [target.mode_value],
                component_id=target.component_id,
                capability=target.mode_capability,
                optimistic_updates=optimistic_updates,
            )
            await self._async_normalize_oven_inputs_for_mode(
                helper=helper,
                target=target,
                raw_mode=raw_option,
            )
            if was_running and current_raw != raw_option:
                await helper._async_start_oven_program()
            return

        await self._async_send_command(
            self.entity_description.command,
            [option],
            optimistic_updates=[
                (
                    self.entity_description.component_id,
                    self.entity_description.capability,
                    self.entity_description.value_path,
                    option,
                )
            ],
        )

    def _raw_oven_options(self) -> list[str]:
        options: list[str] = []
        allowed_raw_options = set(self.entity_description.allowed_raw_options)
        for component_id, capability in self._oven_mode_sources():
            raw_options = self._lookup_path(
                self.entity_description.options_path,
                component_id=component_id,
                capability=capability,
            )
            if isinstance(raw_options, list):
                for value in raw_options:
                    if not isinstance(value, str):
                        continue
                    if allowed_raw_options and value not in allowed_raw_options:
                        continue
                    if value not in options:
                        options.append(value)

            current_raw = self._lookup_path(
                self.entity_description.value_path,
                component_id=component_id,
                capability=capability,
            )
            if (
                isinstance(current_raw, str)
                and (not allowed_raw_options or current_raw in allowed_raw_options)
                and current_raw not in options
            ):
                options.append(current_raw)

        for raw_option in self.entity_description.fallback_options:
            if allowed_raw_options and raw_option not in allowed_raw_options:
                continue
            if raw_option not in options:
                options.append(raw_option)

        if not options:
            options = list(self.entity_description.fallback_options)
        return options

    def _resolve_oven_mode_raw_option(self, option: str) -> str | None:
        language = self._oven_mode_language()
        raw_options = self._raw_oven_options()
        raw_option = denormalize_oven_mode(
            option,
            language=language,
            raw_options=raw_options,
        )
        return raw_option if raw_option in raw_options else None

    def _resolve_oven_mode_target(self, raw_option: str) -> tuple[str, str, str] | None:
        for component_id, capability in self._oven_mode_sources():
            raw_options = self._lookup_path(
                self.entity_description.options_path,
                component_id=component_id,
                capability=capability,
            )
            options = (
                [value for value in raw_options if isinstance(value, str)]
                if isinstance(raw_options, list)
                else []
            )
            if raw_option in self.entity_description.fallback_options and raw_option not in options:
                options.append(raw_option)
            if raw_option in options:
                return component_id, capability, raw_option
        return None

    def _mode_optimistic_updates(
        self,
        *,
        component_id: str,
        capability: str,
        raw_option: str,
    ) -> list[tuple[str, str, tuple[str, ...], str]]:
        optimistic_updates = [
            (
                self.entity_description.component_id,
                self.entity_description.capability,
                self.entity_description.value_path,
                raw_option,
            )
        ]
        if (
            component_id != self.entity_description.component_id
            or capability != self.entity_description.capability
        ):
            optimistic_updates.append(
                (
                    component_id,
                    capability,
                    self.entity_description.value_path,
                    raw_option,
                )
            )
        return optimistic_updates

    async def _async_normalize_oven_inputs_for_mode(
        self,
        *,
        helper,
        target,
        raw_mode: str,
    ) -> None:
        spec = self._oven_mode_spec_for(raw_mode)
        if spec is None:
            return

        timer_minutes = helper._current_timer_minutes()
        resolved_timer = _resolve_mode_timer_minutes(
            spec=spec,
            current_value=timer_minutes,
        )
        if (
            target.timer_capability is not None
            and resolved_timer is not None
            and timer_minutes != resolved_timer
        ):
            timer_payload = format_duration_minutes(resolved_timer)
            await self._async_send_command(
                "setOperationTime",
                [timer_payload],
                component_id=target.component_id,
                capability=target.timer_capability,
                optimistic_updates=helper._mirrored_updates(
                    target=target,
                    capability="samsungce.ovenOperatingState",
                    path=("operationTime", "value"),
                    value=timer_payload,
                ),
            )

        current_unit = self._lookup_path(
            ("ovenSetpoint", "unit"),
            component_id=self.entity_description.component_id,
            capability="ovenSetpoint",
        )
        current_setpoint = helper._current_setpoint_value()
        resolved_setpoint = _resolve_mode_setpoint(
            spec=spec,
            current_value=current_setpoint,
            unit=current_unit if isinstance(current_unit, str) else None,
        )
        if resolved_setpoint is not None and current_setpoint != resolved_setpoint:
            setpoint_value = int(round(resolved_setpoint))
            await self._async_send_command(
                "setOvenSetpoint",
                [setpoint_value],
                component_id=target.component_id,
                capability=target.setpoint_capability,
                optimistic_updates=helper._mirrored_updates(
                    target=target,
                    capability=target.setpoint_capability,
                    path=("ovenSetpoint", "value"),
                    value=setpoint_value,
                ),
            )

    def _oven_mode_sources(self) -> list[tuple[str, str]]:
        sources = [
            (self.entity_description.component_id, self.entity_description.capability),
            ("main", "samsungce.ovenMode"),
            (self.entity_description.component_id, "ovenMode"),
            ("main", "ovenMode"),
        ]
        unique_sources: list[tuple[str, str]] = []
        for source in sources:
            if source not in unique_sources:
                unique_sources.append(source)
        return unique_sources

    def _oven_mode_language(self) -> str:
        return oven_mode_display_language(self.hass.config.language)


def _resolve_mode_timer_minutes(
    *,
    spec: dict[str, object],
    current_value: float | None,
) -> float | None:
    supported_options = spec.get("supportedOptions")
    if not isinstance(supported_options, dict):
        return current_value

    operation_time = supported_options.get("operationTime")
    if not isinstance(operation_time, dict):
        return current_value

    minimum = parse_duration_minutes(operation_time.get("min"))
    maximum = parse_duration_minutes(operation_time.get("max"))
    default_value = parse_duration_minutes(operation_time.get("default"))
    if minimum is None or maximum is None:
        return current_value
    resolved_default = default_value if default_value is not None else minimum
    if current_value is None or current_value < minimum or current_value > maximum:
        return resolved_default
    return current_value


def _resolve_mode_setpoint(
    *,
    spec: dict[str, object],
    current_value: float | None,
    unit: str | None,
) -> float | None:
    supported_options = spec.get("supportedOptions")
    if not isinstance(supported_options, dict):
        return current_value

    temperature = supported_options.get("temperature")
    if not isinstance(temperature, dict):
        return current_value

    unit_key = unit if unit in {"C", "F"} else "C"
    range_by_unit = temperature.get(unit_key)
    if not isinstance(range_by_unit, dict):
        range_by_unit = temperature.get("C")
    if not isinstance(range_by_unit, dict):
        return current_value

    minimum = coerce_numeric_value(range_by_unit.get("min"))
    maximum = coerce_numeric_value(range_by_unit.get("max"))
    default_value = coerce_numeric_value(range_by_unit.get("default"))
    if minimum is None or maximum is None:
        return current_value
    resolved_default = default_value if default_value is not None else minimum
    if current_value is None or current_value < minimum or current_value > maximum:
        return resolved_default
    return current_value
