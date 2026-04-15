from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

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

LOGGER = logging.getLogger(__name__)

DEFAULT_OVEN_TIMER_RANGE = (0.0, 720.0, 1.0)
DEFAULT_OVEN_TEMPERATURE_RANGE = (30.0, 300.0, 5.0)

PRESTART_VERIFY_TIMEOUT_SECONDS = 3.0
POSTSTART_VERIFY_TIMEOUT_SECONDS = 10.0
VERIFY_INTERVAL_SECONDS = 1.0
MAX_START_ATTEMPTS = 2

ACTIVE_MACHINE_STATES = {"running", "paused"}
IDLE_JOB_STATES = {"ready", "finished"}
IDLE_CAVITY_STATES = {"off"}


@dataclass(frozen=True, slots=True)
class OvenControlTarget:
    component_id: str
    command_path: Literal["standard", "fallback"]
    mode_capability: str
    mode_value: str
    timer_capability: str | None
    setpoint_capability: str
    start_capability: str
    start_mode_argument: str | None
    supported_start_modes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OvenStartValues:
    raw_mode: str
    mode_argument: str | None
    timer_minutes: float
    timer_seconds: int
    timer_payload: str
    setpoint: int
    timer_bounds: tuple[float, float, float]
    temperature_bounds: tuple[float, float, float]


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

        raw_mode = self._preferred_oven_input_mode_raw()
        if raw_mode is None:
            raise HomeAssistantError("Select an oven mode before starting the oven.")

        spec = self._oven_mode_spec_for(raw_mode) or self._current_oven_mode_spec()
        if not _supports_operation(spec, "start"):
            raise HomeAssistantError("The selected oven mode cannot be started from SmartThings.")

        target = self._resolve_oven_control_target(raw_mode)
        values = self._build_start_values(raw_mode=raw_mode, spec=spec, target=target)

        failure_message: str | None = None
        for attempt in range(1, MAX_START_ATTEMPTS + 1):
            responses: dict[str, Any] = {}
            prestart_observed_state: dict[str, Any] = {}
            poststart_observed_state: dict[str, Any] = {}
            response_status = "unknown"

            try:
                responses = await self._async_apply_prestart_commands(target=target, values=values)
                prestart_observed_state = await self._async_verify_prestart_state(
                    target=target,
                    values=values,
                )
                if not self._prestart_state_is_confirmed(
                    target=target,
                    prestart_observed_state=prestart_observed_state,
                ):
                    response_status = "prestart_not_confirmed"
                    failure_message = self._prestart_failure_message(
                        target=target,
                        prestart_observed_state=prestart_observed_state,
                    )
                    raise HomeAssistantError(failure_message)

                responses["start"] = await self._async_send_start_command(
                    target=target,
                    values=values,
                )
                running, poststart_observed_state = await self._async_verify_running_state(
                    target=target
                )
                if running:
                    response_status = "running"
                    self._log_start_attempt(
                        attempt=attempt,
                        target=target,
                        values=values,
                        response_status=response_status,
                        responses=responses,
                        prestart_observed_state=prestart_observed_state,
                        poststart_observed_state=poststart_observed_state,
                    )
                    return

                response_status = (
                    "idle_after_retry" if attempt >= MAX_START_ATTEMPTS else "idle_after_start"
                )
                failure_message = self._idle_start_failure_message(target=target, values=values)
            except Exception as err:
                if response_status == "unknown":
                    response_status = "command_error"
                failure_message = failure_message or str(err)
                self._log_start_attempt(
                    attempt=attempt,
                    target=target,
                    values=values,
                    response_status=response_status,
                    responses=responses,
                    prestart_observed_state=prestart_observed_state,
                    poststart_observed_state=poststart_observed_state,
                    error=err,
                )
                if attempt >= MAX_START_ATTEMPTS or response_status != "idle_after_start":
                    raise
                continue

            self._log_start_attempt(
                attempt=attempt,
                target=target,
                values=values,
                response_status=response_status,
                responses=responses,
                prestart_observed_state=prestart_observed_state,
                poststart_observed_state=poststart_observed_state,
            )

            if attempt >= MAX_START_ATTEMPTS:
                break

        raise HomeAssistantError(
            failure_message or self._idle_start_failure_message(target=target, values=values)
        )

    async def _async_stop_oven_program(self) -> None:
        self._require_remote_control_enabled()
        component_id, capability, optimistic_updates = self._resolve_stop_target()
        await self._async_send_command(
            "stop",
            [],
            component_id=component_id,
            capability=capability,
            optimistic_updates=optimistic_updates,
        )

    def _resolve_oven_control_target(self, raw_mode: str) -> OvenControlTarget:
        preferred_components = self._preferred_control_components()
        standard_candidates: list[
            tuple[str, str | None, tuple[str, ...], tuple[str, str] | None]
        ] = []
        fallback_candidates: list[tuple[str, tuple[str, ...]]] = []

        for component_id in preferred_components:
            component_capabilities = self._component_capabilities(component_id)
            standard_supported_modes = tuple(self._supported_modes(component_id, "ovenMode"))
            if {"ovenMode", "ovenOperatingState", "ovenSetpoint"}.issubset(component_capabilities):
                start_mode = resolve_standard_oven_start_mode(raw_mode, standard_supported_modes)
                mode_command = self._resolve_mode_command(
                    component_id=component_id,
                    raw_mode=raw_mode,
                    start_mode=start_mode,
                )
                standard_candidates.append(
                    (component_id, start_mode, standard_supported_modes, mode_command)
                )

            if {
                "samsungce.ovenMode",
                "samsungce.ovenOperatingState",
                "ovenSetpoint",
            }.issubset(component_capabilities):
                fallback_candidates.append(
                    (
                        component_id,
                        tuple(self._supported_modes(component_id, "samsungce.ovenMode")),
                    )
                )

        for component_id, start_mode, supported_start_modes, mode_command in standard_candidates:
            if start_mode is None or mode_command is None:
                continue
            mode_capability, mode_value = mode_command
            timer_capability = (
                "samsungce.ovenOperatingState"
                if self._component_has_capability(component_id, "samsungce.ovenOperatingState")
                else None
            )
            return OvenControlTarget(
                component_id=component_id,
                command_path="standard",
                mode_capability=mode_capability,
                mode_value=mode_value,
                timer_capability=timer_capability,
                setpoint_capability="ovenSetpoint",
                start_capability="ovenOperatingState",
                start_mode_argument=start_mode,
                supported_start_modes=supported_start_modes,
            )

        if standard_candidates:
            component_id, start_mode, supported_start_modes, mode_command = standard_candidates[0]
            if start_mode is None:
                supported_modes_text = ", ".join(supported_start_modes) or "none"
                raise HomeAssistantError(
                    "The selected oven mode has no supported SmartThings start mapping on "
                    f"{component_id}. Supported start modes: {supported_modes_text}."
                )
            if mode_command is None:
                raise HomeAssistantError(
                    "The selected oven mode cannot be set on the resolved "
                    f"control component {component_id}."
                )

        for component_id, supported_modes in fallback_candidates:
            if raw_mode not in supported_modes:
                continue
            return OvenControlTarget(
                component_id=component_id,
                command_path="fallback",
                mode_capability="samsungce.ovenMode",
                mode_value=raw_mode,
                timer_capability="samsungce.ovenOperatingState",
                setpoint_capability="ovenSetpoint",
                start_capability="samsungce.ovenOperatingState",
                start_mode_argument=None,
                supported_start_modes=supported_modes,
            )

        if fallback_candidates:
            component_id, supported_modes = fallback_candidates[0]
            supported_modes_text = ", ".join(supported_modes) or "none"
            raise HomeAssistantError(
                "The selected oven mode is not supported by the fallback "
                "SmartThings control path on "
                f"{component_id}. Supported modes: {supported_modes_text}."
            )

        raise HomeAssistantError("No supported SmartThings oven control component was found.")

    def _resolve_stop_target(
        self,
    ) -> tuple[str, str, list[tuple[str, str, Sequence[str], Any]]]:
        preferred_components = self._preferred_control_components()
        for capability, path, value in (
            ("ovenOperatingState", ("machineState", "value"), "ready"),
            ("samsungce.ovenOperatingState", ("operatingState", "value"), "ready"),
        ):
            for component_id in preferred_components:
                if not self._component_has_capability(component_id, capability):
                    continue
                optimistic_updates = [(component_id, capability, path, value)]
                if component_id != self.entity_description.component_id:
                    optimistic_updates.append(
                        (self.entity_description.component_id, capability, path, value)
                    )
                return component_id, capability, optimistic_updates
        raise HomeAssistantError("No supported SmartThings oven stop capability was found.")

    def _build_start_values(
        self,
        *,
        raw_mode: str,
        spec: dict[str, Any] | None,
        target: OvenControlTarget,
    ) -> OvenStartValues:
        timer_bounds, timer_bounds_fallback = self._timer_bounds(spec)
        if timer_bounds_fallback:
            LOGGER.info(
                "Advanced SmartThings oven start is using timer fallback bounds "
                "for %s: min=%s max=%s step=%s",
                self._device.device_id,
                timer_bounds[0],
                timer_bounds[1],
                timer_bounds[2],
            )

        temperature_bounds, temperature_bounds_fallback = self._temperature_bounds(spec)
        if temperature_bounds_fallback:
            LOGGER.info(
                "Advanced SmartThings oven start is using temperature fallback "
                "bounds for %s: min=%s max=%s step=%s",
                self._device.device_id,
                temperature_bounds[0],
                temperature_bounds[1],
                temperature_bounds[2],
            )

        timer_minutes = self._current_timer_minutes()
        if timer_minutes is None:
            raise HomeAssistantError("Set the oven timer before starting the oven.")
        if timer_minutes <= 0:
            raise HomeAssistantError("Set the oven timer above 0 minutes before starting the oven.")
        _validate_numeric_range(
            label="Oven timer",
            value=timer_minutes,
            minimum=timer_bounds[0],
            maximum=timer_bounds[1],
        )

        current_setpoint = self._current_setpoint_value()
        if current_setpoint is None:
            raise HomeAssistantError("Set the oven temperature before starting the oven.")
        if current_setpoint <= 0:
            raise HomeAssistantError("Set the oven temperature above 0 before starting the oven.")
        _validate_numeric_range(
            label="Oven temperature",
            value=current_setpoint,
            minimum=temperature_bounds[0],
            maximum=temperature_bounds[1],
        )

        mode_argument = target.start_mode_argument
        if target.command_path == "standard":
            if mode_argument is None:
                raise HomeAssistantError(
                    "The selected oven mode "
                    f"{raw_mode} has no supported standard SmartThings "
                    "start argument."
                )
            if mode_argument not in target.supported_start_modes:
                raise HomeAssistantError(
                    f"The SmartThings start mode {mode_argument} is not "
                    f"supported on {target.component_id}."
                )

        timer_payload = format_duration_minutes(timer_minutes)
        timer_seconds = max(1, int(round(timer_minutes * 60)))

        return OvenStartValues(
            raw_mode=raw_mode,
            mode_argument=mode_argument,
            timer_minutes=timer_minutes,
            timer_seconds=timer_seconds,
            timer_payload=timer_payload,
            setpoint=int(round(current_setpoint)),
            timer_bounds=timer_bounds,
            temperature_bounds=temperature_bounds,
        )

    async def _async_apply_prestart_commands(
        self,
        *,
        target: OvenControlTarget,
        values: OvenStartValues,
    ) -> dict[str, Any]:
        responses: dict[str, Any] = {}
        mode_updates = self._mirrored_updates(
            target=target,
            capability=target.mode_capability,
            path=("ovenMode", "value"),
            value=target.mode_value,
        )
        responses["set_mode"] = await self._async_send_command(
            "setOvenMode",
            [target.mode_value],
            component_id=target.component_id,
            capability=target.mode_capability,
            optimistic_updates=mode_updates,
        )

        timer_updates = self._mirrored_updates(
            target=target,
            capability="samsungce.ovenOperatingState",
            path=("operationTime", "value"),
            value=values.timer_payload,
        )
        if target.timer_capability is not None:
            responses["set_timer"] = await self._async_send_command(
                "setOperationTime",
                [values.timer_payload],
                component_id=target.component_id,
                capability=target.timer_capability,
                optimistic_updates=timer_updates,
            )
        else:
            responses["set_timer"] = {"status": "skipped"}

        setpoint_updates = self._mirrored_updates(
            target=target,
            capability=target.setpoint_capability,
            path=("ovenSetpoint", "value"),
            value=values.setpoint,
        )
        responses["set_setpoint"] = await self._async_send_command(
            "setOvenSetpoint",
            [values.setpoint],
            component_id=target.component_id,
            capability=target.setpoint_capability,
            optimistic_updates=setpoint_updates,
        )
        return responses

    async def _async_send_start_command(
        self,
        *,
        target: OvenControlTarget,
        values: OvenStartValues,
    ) -> dict[str, Any]:
        arguments: list[Any]
        if target.command_path == "standard":
            arguments = [values.mode_argument, values.timer_seconds, values.setpoint]
        else:
            arguments = []

        return await self._async_send_command(
            "start",
            arguments,
            component_id=target.component_id,
            capability=target.start_capability,
        )

    async def _async_verify_prestart_state(
        self,
        *,
        target: OvenControlTarget,
        values: OvenStartValues,
    ) -> dict[str, Any]:
        return await self._async_poll_status(
            timeout=PRESTART_VERIFY_TIMEOUT_SECONDS,
            poll_interval=VERIFY_INTERVAL_SECONDS,
            predicate=lambda observed: self._prestart_state_is_confirmed(
                target=target,
                prestart_observed_state=observed,
            ),
            target=target,
            values=values,
        )

    async def _async_verify_running_state(
        self,
        *,
        target: OvenControlTarget,
    ) -> tuple[bool, dict[str, Any]]:
        observed = await self._async_poll_status(
            timeout=POSTSTART_VERIFY_TIMEOUT_SECONDS,
            poll_interval=VERIFY_INTERVAL_SECONDS,
            predicate=self._observed_state_is_running,
            target=target,
        )
        return self._observed_state_is_running(observed), observed

    async def _async_poll_status(
        self,
        *,
        timeout: float,
        poll_interval: float,
        predicate,
        target: OvenControlTarget,
        values: OvenStartValues | None = None,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        observed_state = self._observed_oven_state(
            status=self.coordinator.data.get(self._device.device_id),
            target=target,
            values=values,
        )
        while True:
            if predicate(observed_state):
                return observed_state
            if asyncio.get_running_loop().time() >= deadline:
                return observed_state
            await asyncio.sleep(poll_interval)
            status = await self._async_refresh_device_status()
            observed_state = self._observed_oven_state(
                status=status,
                target=target,
                values=values,
            )

    def _observed_oven_state(
        self,
        *,
        status: dict[str, Any] | None,
        target: OvenControlTarget,
        values: OvenStartValues | None = None,
    ) -> dict[str, Any]:
        components: dict[str, Any] = {}
        for component_id in self._observed_component_ids(target.component_id):
            components[component_id] = {
                "samsung_mode": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="samsungce.ovenMode",
                    path=("ovenMode", "value"),
                ),
                "standard_mode": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="ovenMode",
                    path=("ovenMode", "value"),
                ),
                "samsung_operating_state": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="samsungce.ovenOperatingState",
                    path=("operatingState", "value"),
                ),
                "samsung_job_state": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="samsungce.ovenOperatingState",
                    path=("ovenJobState", "value"),
                ),
                "samsung_operation_time": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="samsungce.ovenOperatingState",
                    path=("operationTime", "value"),
                ),
                "standard_machine_state": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="ovenOperatingState",
                    path=("machineState", "value"),
                ),
                "standard_job_state": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="ovenOperatingState",
                    path=("ovenJobState", "value"),
                ),
                "standard_operation_time": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="ovenOperatingState",
                    path=("operationTime", "value"),
                ),
                "setpoint": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="ovenSetpoint",
                    path=("ovenSetpoint", "value"),
                ),
                "cavity_status": self._status_lookup_path(
                    status,
                    component_id=component_id,
                    capability="custom.ovenCavityStatus",
                    path=("ovenCavityStatus", "value"),
                ),
            }

        observed = {
            "components": components,
            "prestart": {},
        }
        if values is not None:
            target_state = components.get(target.component_id, {})
            timer_match = False
            if target.timer_capability == "samsungce.ovenOperatingState":
                timer_match = (
                    parse_duration_minutes(target_state.get("samsung_operation_time"))
                    == values.timer_minutes
                )
            elif target.command_path == "standard":
                timer_match = coerce_numeric_value(
                    target_state.get("standard_operation_time")
                ) == float(values.timer_seconds)

            setpoint_match = coerce_numeric_value(target_state.get("setpoint")) == float(
                values.setpoint
            )
            mode_match = False
            if target.mode_capability == "samsungce.ovenMode":
                mode_match = target_state.get("samsung_mode") == target.mode_value
            elif target.mode_capability == "ovenMode":
                mode_match = target_state.get("standard_mode") == target.mode_value

            observed["prestart"] = {
                "mode_confirmed": mode_match,
                "timer_confirmed": timer_match,
                "setpoint_confirmed": setpoint_match,
            }
        return observed

    def _prestart_state_is_confirmed(
        self,
        *,
        target: OvenControlTarget,
        prestart_observed_state: dict[str, Any],
    ) -> bool:
        prestart = prestart_observed_state.get("prestart", {})
        if not isinstance(prestart, dict):
            return False
        mode_confirmed = bool(prestart.get("mode_confirmed"))
        timer_confirmed = bool(prestart.get("timer_confirmed"))
        setpoint_confirmed = bool(prestart.get("setpoint_confirmed"))
        if target.timer_capability is None:
            return mode_confirmed and setpoint_confirmed
        return mode_confirmed and timer_confirmed and setpoint_confirmed

    def _observed_state_is_running(self, observed_state: dict[str, Any]) -> bool:
        components = observed_state.get("components")
        if not isinstance(components, dict):
            return False
        for component_state in components.values():
            if not isinstance(component_state, dict):
                continue
            if (
                normalize_state_value(component_state.get("standard_machine_state"))
                in ACTIVE_MACHINE_STATES
            ):
                return True
            if (
                normalize_state_value(component_state.get("samsung_operating_state"))
                in ACTIVE_MACHINE_STATES
            ):
                return True
            if _job_state_is_active(component_state.get("standard_job_state")):
                return True
            if _job_state_is_active(component_state.get("samsung_job_state")):
                return True
            if _cavity_state_is_active(component_state.get("cavity_status")):
                return True
        return False

    def _preferred_control_components(self) -> list[str]:
        ordered = ["main", self.entity_description.component_id]
        for raw_component in self._device.raw.get("components", []):
            if not isinstance(raw_component, dict):
                continue
            component_id = raw_component.get("id")
            if isinstance(component_id, str) and component_id not in ordered:
                ordered.append(component_id)
        return ordered

    def _component_capabilities(self, component_id: str) -> set[str]:
        for raw_component in self._device.raw.get("components", []):
            if not isinstance(raw_component, dict):
                continue
            if raw_component.get("id") != component_id:
                continue
            capabilities: set[str] = set()
            for raw_capability in raw_component.get("capabilities", []):
                if isinstance(raw_capability, dict):
                    capability_id = raw_capability.get("id")
                    if isinstance(capability_id, str):
                        capabilities.add(capability_id)
            return capabilities
        return set()

    def _component_has_capability(self, component_id: str, capability_id: str) -> bool:
        return capability_id in self._component_capabilities(component_id)

    def _supported_modes(self, component_id: str, capability: str) -> list[str]:
        raw_supported_modes = self._lookup_path(
            ("supportedOvenModes", "value"),
            component_id=component_id,
            capability=capability,
        )
        if not isinstance(raw_supported_modes, list):
            return []
        return [value for value in raw_supported_modes if isinstance(value, str)]

    def _resolve_mode_command(
        self,
        *,
        component_id: str,
        raw_mode: str,
        start_mode: str | None,
    ) -> tuple[str, str] | None:
        samsung_modes = self._supported_modes(component_id, "samsungce.ovenMode")
        if raw_mode in samsung_modes:
            return "samsungce.ovenMode", raw_mode

        standard_modes = self._supported_modes(component_id, "ovenMode")
        if start_mode is not None and start_mode in standard_modes:
            return "ovenMode", start_mode
        return None

    def _current_timer_minutes(self) -> float | None:
        return self._actual_oven_timer_minutes()

    def _current_setpoint_value(self) -> float | None:
        return self._actual_oven_setpoint_value()

    def _temperature_bounds(
        self,
        spec: dict[str, Any] | None,
    ) -> tuple[tuple[float, float, float], bool]:
        supported_options = spec.get("supportedOptions") if isinstance(spec, dict) else None
        if isinstance(supported_options, dict):
            temperature_options = supported_options.get("temperature")
            if isinstance(temperature_options, dict):
                raw_unit = self._lookup_path(
                    ("ovenSetpoint", "unit"),
                    component_id=self.entity_description.component_id,
                    capability="ovenSetpoint",
                )
                preferred_unit = "C"
                resolved_unit = self._actual_oven_setpoint_unit()
                if resolved_unit == "°F":
                    preferred_unit = "F"
                elif resolved_unit == "°C":
                    preferred_unit = "C"
                elif raw_unit in {"C", "F"}:
                    preferred_unit = raw_unit
                by_unit = temperature_options.get(preferred_unit)
                if not isinstance(by_unit, dict):
                    by_unit = temperature_options.get("C")
                if isinstance(by_unit, dict):
                    minimum = by_unit.get("min")
                    maximum = by_unit.get("max")
                    resolution = by_unit.get("resolution", 1)
                    if isinstance(minimum, int | float) and isinstance(maximum, int | float):
                        step = float(resolution) if isinstance(resolution, int | float) else 1.0
                        return (float(minimum), float(maximum), step), False
        return DEFAULT_OVEN_TEMPERATURE_RANGE, True

    def _timer_bounds(
        self,
        spec: dict[str, Any] | None,
    ) -> tuple[tuple[float, float, float], bool]:
        supported_options = spec.get("supportedOptions") if isinstance(spec, dict) else None
        if isinstance(supported_options, dict):
            operation_time = supported_options.get("operationTime")
            if isinstance(operation_time, dict):
                minimum = parse_duration_minutes(operation_time.get("min"))
                maximum = parse_duration_minutes(operation_time.get("max"))
                resolution = parse_duration_minutes(operation_time.get("resolution")) or 1.0
                if minimum is not None and maximum is not None:
                    return (minimum, maximum, resolution), False
        return DEFAULT_OVEN_TIMER_RANGE, True

    def _mirrored_updates(
        self,
        *,
        target: OvenControlTarget,
        capability: str,
        path: Sequence[str],
        value: Any,
    ) -> list[tuple[str, str, Sequence[str], Any]]:
        updates = [(target.component_id, capability, path, value)]
        if target.component_id != self.entity_description.component_id:
            updates.append((self.entity_description.component_id, capability, path, value))
        return updates

    def _status_lookup_path(
        self,
        status: dict[str, Any] | None,
        *,
        component_id: str,
        capability: str,
        path: Sequence[str],
    ) -> Any:
        if not isinstance(status, dict):
            return None
        components = status.get("components")
        if not isinstance(components, dict):
            return None
        component = components.get(component_id)
        if not isinstance(component, dict):
            return None
        capability_payload = component.get(capability)
        if not isinstance(capability_payload, dict):
            return None
        current: Any = capability_payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _observed_component_ids(self, target_component_id: str) -> list[str]:
        component_ids: list[str] = []
        for component_id in (target_component_id, self.entity_description.component_id, "main"):
            if component_id not in component_ids:
                component_ids.append(component_id)
        return component_ids

    def _prestart_failure_message(
        self,
        *,
        target: OvenControlTarget,
        prestart_observed_state: dict[str, Any],
    ) -> str:
        prestart = prestart_observed_state.get("prestart", {})
        return (
            "SmartThings did not confirm the oven mode, timer, and temperature on "
            f"{target.component_id} before sending the start command. "
            f"Observed prestart state: {prestart}"
        )

    def _idle_start_failure_message(
        self,
        *,
        target: OvenControlTarget,
        values: OvenStartValues,
    ) -> str:
        mode_argument = values.mode_argument or values.raw_mode
        return (
            "The oven remained idle after SmartThings start attempts. "
            f"path={target.command_path} component={target.component_id} "
            f"mode_argument={mode_argument} timer_minutes={values.timer_minutes} "
            f"setpoint={values.setpoint}"
        )

    def _log_start_attempt(
        self,
        *,
        attempt: int,
        target: OvenControlTarget,
        values: OvenStartValues,
        response_status: str,
        responses: dict[str, Any],
        prestart_observed_state: dict[str, Any],
        poststart_observed_state: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        payload = {
            "attempt": attempt,
            "component": target.component_id,
            "mode_argument": values.mode_argument or values.raw_mode,
            "timer_minutes": values.timer_minutes,
            "setpoint": values.setpoint,
            "command_path": target.command_path,
            "response_status": response_status,
            "response_payload": responses,
            "prestart_observed_state": prestart_observed_state,
            "post_start_observed_state": poststart_observed_state,
        }
        if error is not None:
            payload["error"] = str(error)
        LOGGER.info("advanced_smartthings oven_start_attempt %s", json.dumps(payload, default=str))


def _supports_operation(spec: dict[str, Any] | None, operation: str) -> bool:
    if not isinstance(spec, dict):
        return True
    supported_operations = spec.get("supportedOperations")
    if not isinstance(supported_operations, list):
        return True
    return operation in [value for value in supported_operations if isinstance(value, str)]


def _validate_numeric_range(
    *,
    label: str,
    value: float,
    minimum: float,
    maximum: float,
) -> None:
    if value < minimum or value > maximum:
        raise HomeAssistantError(
            f"{label} must be between {minimum:g} and {maximum:g}. Current value: {value:g}."
        )


def normalize_state_value(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    return raw_value.casefold()


def _job_state_is_active(raw_value: Any) -> bool:
    normalized = normalize_state_value(raw_value)
    if normalized is None:
        return False
    return normalized not in IDLE_JOB_STATES


def _cavity_state_is_active(raw_value: Any) -> bool:
    normalized = normalize_state_value(raw_value)
    if normalized is None:
        return False
    return normalized not in IDLE_CAVITY_STATES
