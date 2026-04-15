from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_TOKEN
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.advanced_smartthings.const import (
    CONF_LOCATION_IDS,
    CONF_SELECTED_DEVICE_IDS,
    DOMAIN,
)

from .conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    COOKTOP_DEVICE,
    COOKTOP_STATUS,
    FRIDGE_DEVICE,
    FRIDGE_STATUS,
    OVEN_DEVICE,
    OVEN_SETPOINT_DEFINITION,
    OVEN_STATUS,
    OVEN_STATUS_REMOTE_DISABLED,
    SAMSUNG_OVEN_MODE_DEFINITION,
    THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    TOKEN_PAYLOAD,
)


def _fake_api(devices: list[dict], status_by_device: dict[str, dict]) -> AsyncMock:
    api = AsyncMock()
    api.async_get_devices.return_value = devices
    api.async_send_command.return_value = {}
    api.async_send_commands.return_value = {}
    api.async_prefetch_capability_definitions.return_value = {
        ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
        ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
        ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    }

    async def get_status(device_id: str) -> dict:
        return status_by_device[device_id]

    api.async_get_device_status.side_effect = get_status
    return api


def _oven_status_with_running_component(
    status: dict[str, dict],
    *,
    component_id: str,
) -> dict[str, dict]:
    updated = deepcopy(status)
    component = updated["components"][component_id]
    component.setdefault("samsungce.ovenOperatingState", {})["operatingState"] = {
        "value": "running"
    }
    component["samsungce.ovenOperatingState"]["ovenJobState"] = {"value": "warming"}
    component.setdefault("ovenOperatingState", {})["machineState"] = {"value": "running"}
    component["ovenOperatingState"]["ovenJobState"] = {"value": "warming"}
    return updated


def _oven_device_with_standard_start() -> dict:
    cavity_component = deepcopy(OVEN_DEVICE["components"][1])
    main_component = deepcopy(OVEN_DEVICE["components"][0])
    main_component["capabilities"] = [
        *main_component["capabilities"],
        {"id": "samsungce.ovenMode", "version": 1},
        {"id": "samsungce.ovenOperatingState", "version": 1},
        {"id": "ovenMode", "version": 1},
        {"id": "ovenOperatingState", "version": 1},
        {"id": "ovenSetpoint", "version": 1},
    ]
    return {
        **OVEN_DEVICE,
        "components": [cavity_component, main_component],
    }


def _oven_status_with_standard_start() -> dict:
    return {
        "components": {
            "main": {
                **OVEN_STATUS["components"]["main"],
                "samsungce.ovenMode": {
                    "supportedOvenModes": {"value": ["Convection", "KeepWarm"]},
                    "ovenMode": {"value": "NoOperation"},
                },
                "samsungce.ovenOperatingState": {
                    "operationTime": {"value": "00:00:00"},
                    "operatingState": {"value": "ready"},
                    "ovenJobState": {"value": "ready"},
                },
                "ovenMode": {
                    "supportedOvenModes": {"value": ["Others", "ConvectionBake", "warming"]},
                    "ovenMode": {"value": "Others"},
                },
                "ovenOperatingState": {
                    "operationTime": {"value": 0},
                    "machineState": {"value": "ready"},
                    "progress": {"value": 0, "unit": "%"},
                    "ovenJobState": {"value": "ready"},
                },
                "ovenSetpoint": {
                    "ovenSetpoint": {"value": 0, "unit": "C"},
                },
            },
            "cavity-01": {
                **OVEN_STATUS["components"]["cavity-01"],
                "samsungce.ovenMode": {
                    "supportedOvenModes": {"value": ["Convection", "KeepWarm"]},
                    "ovenMode": {"value": "NoOperation"},
                },
                "samsungce.ovenOperatingState": {
                    "operationTime": {"value": "00:00:00"},
                    "operatingState": {"value": "ready"},
                    "ovenJobState": {"value": "ready"},
                },
                "ovenSetpoint": {
                    "ovenSetpoint": {"value": 0, "unit": "C"},
                },
            },
        }
    }


async def test_setup_entry_creates_supported_native_entities(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    fake_api = _fake_api(
        [OVEN_DEVICE, FRIDGE_DEVICE, COOKTOP_DEVICE],
        {
            "device-oven-1": OVEN_STATUS,
            "device-fridge-1": FRIDGE_STATUS,
            "device-cooktop-1": COOKTOP_STATUS,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("select.backofen_program").state == "Bake"
        assert hass.states.get("sensor.backofen_program").state == "Off"
        assert hass.states.get("sensor.backofen_timer").state == "90.0"
        assert hass.states.get("sensor.backofen_target_temperature").state == "180"
        assert hass.states.get("binary_sensor.backofen_remote_controllable").state == "on"
        assert hass.states.get("binary_sensor.backofen_running").state == "off"
        assert hass.states.get("switch.backofen_running").state == "off"
        assert hass.states.get("sensor.backofen_current_temperature").state == "33"
        assert hass.states.get("number.backofen_timer").state == "90.0"
        assert hass.states.get("number.backofen_target_temperature").state == "180.0"
        assert hass.states.get("switch.backofen_lamp").state == "off"

        assert hass.states.get("binary_sensor.kuhlschrank_refrigerator_door").state == "off"
        assert hass.states.get("binary_sensor.kuhlschrank_freezer_door").state == "on"
        assert hass.states.get("number.kuhlschrank_refrigerator_temperature").state == "6.0"
        assert hass.states.get("number.kuhlschrank_freezer_temperature").state == "-18.0"
        assert hass.states.get("sensor.kuhlschrank_power_consumption").state == "1458"
        assert hass.states.get("sensor.kuhlschrank_water_filter_usage").state == "13"
        assert hass.states.get("binary_sensor.kochfeld_running").state == "off"

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_running_oven_program_prefers_active_mode_over_no_operation(
    hass,
    mock_config_entry,
) -> None:
    hass.config.language = "de"
    mock_config_entry.add_to_hass(hass)

    oven_with_standard_start = _oven_device_with_standard_start()
    running_status = _oven_status_with_standard_start()
    running_status["components"]["main"]["ovenMode"]["ovenMode"] = {"value": "ConvectionBake"}
    running_status["components"]["main"]["ovenOperatingState"]["machineState"] = {
        "value": "running"
    }
    running_status["components"]["main"]["ovenOperatingState"]["ovenJobState"] = {
        "value": "warming"
    }

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": running_status},
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("sensor.backofen_program").state == "Heißluft"
        assert hass.states.get("select.backofen_program").state == "Heißluft"

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_running_oven_live_state_prefers_active_component_values(
    hass,
    mock_config_entry,
) -> None:
    hass.config.language = "de"
    mock_config_entry.add_to_hass(hass)

    oven_with_standard_start = _oven_device_with_standard_start()
    running_status = _oven_status_with_standard_start()
    running_status["components"]["main"]["ovenMode"]["ovenMode"] = {"value": "ConvectionBake"}
    running_status["components"]["main"]["ovenOperatingState"]["machineState"] = {
        "value": "running"
    }
    running_status["components"]["main"]["ovenOperatingState"]["ovenJobState"] = {
        "value": "warming"
    }
    running_status["components"]["main"]["ovenOperatingState"]["operationTime"] = {"value": 1800}
    running_status["components"]["main"]["ovenSetpoint"]["ovenSetpoint"] = {
        "value": 210,
        "unit": "C",
    }
    running_status["components"]["cavity-01"]["samsungce.ovenMode"]["ovenMode"] = {
        "value": "NoOperation"
    }
    running_status["components"]["cavity-01"]["samsungce.ovenOperatingState"]["operatingState"] = {
        "value": "ready"
    }
    running_status["components"]["cavity-01"]["samsungce.ovenOperatingState"]["ovenJobState"] = {
        "value": "ready"
    }
    running_status["components"]["cavity-01"]["samsungce.ovenOperatingState"]["operationTime"] = {
        "value": "00:00:00"
    }
    running_status["components"]["cavity-01"]["ovenSetpoint"]["ovenSetpoint"] = {
        "value": 0,
        "unit": "C",
    }

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": running_status},
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("sensor.backofen_program").state == "Heißluft"
        assert hass.states.get("select.backofen_program").state == "Heißluft"
        assert hass.states.get("sensor.backofen_target_temperature").state == "210"
        assert hass.states.get("number.backofen_target_temperature").state == "210.0"
        assert hass.states.get("sensor.backofen_timer").state == "30.0"
        assert hass.states.get("number.backofen_timer").state == "30.0"
        assert hass.states.get("binary_sensor.backofen_running").state == "on"
        assert hass.states.get("switch.backofen_running").state == "on"

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_timer_has_safe_bounds_when_mode_spec_lacks_operation_time(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_without_timer_spec = {
        "components": {
            **OVEN_STATUS["components"],
            "main": {
                **OVEN_STATUS["components"]["main"],
                "samsungce.kitchenModeSpecification": {
                    "specification": {
                        "value": {
                            "single": [
                                {
                                    "mode": "Convection",
                                    "supportedOptions": {
                                        "temperature": {
                                            "C": {
                                                "min": 30,
                                                "max": 275,
                                                "default": 160,
                                                "resolution": 5,
                                            }
                                        }
                                    },
                                }
                            ]
                        }
                    }
                },
            },
        }
    }

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": oven_without_timer_spec},
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Bake"},
            blocking=True,
        )

        timer_state = hass.states.get("number.backofen_timer")
        assert timer_state is not None
        assert timer_state.attributes["min"] == 0
        assert timer_state.attributes["max"] == 720
        assert timer_state.attributes["step"] == 1

        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 0},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "cavity-01",
            "samsungce.ovenOperatingState",
            "setOperationTime",
            ["00:00:00"],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_temperature_has_safe_bounds_when_mode_spec_lacks_temperature(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_without_temperature_spec = {
        "components": {
            **OVEN_STATUS["components"],
            "main": {
                **OVEN_STATUS["components"]["main"],
                "samsungce.kitchenModeSpecification": {
                    "specification": {
                        "value": {
                            "single": [
                                {
                                    "mode": "Convection",
                                    "supportedOptions": {
                                        "operationTime": {
                                            "min": "00:05:00",
                                            "max": "04:00:00",
                                            "default": "00:30:00",
                                            "resolution": "00:05:00",
                                        }
                                    },
                                }
                            ]
                        }
                    }
                },
            },
        }
    }

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": oven_without_temperature_spec},
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Bake"},
            blocking=True,
        )

        temperature_state = hass.states.get("number.backofen_target_temperature")
        assert temperature_state is not None
        assert temperature_state.attributes["min"] == 30
        assert temperature_state.attributes["max"] == 300
        assert temperature_state.attributes["step"] == 5

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_power_switch_uses_standard_start_when_device_supports_it(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    oven_with_standard_start = _oven_device_with_standard_start()
    oven_with_standard_start_status = _oven_status_with_standard_start()

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": oven_with_standard_start_status},
    )
    start_calls = 0

    async def send_command(
        device_id: str,
        component_id: str,
        capability: str,
        command: str,
        arguments: list | None = None,
    ) -> dict:
        nonlocal start_calls
        if capability == "ovenOperatingState" and command == "start":
            start_calls += 1
        return {}

    async def get_status(device_id: str) -> dict:
        if start_calls >= 1:
            return _oven_status_with_running_component(
                oven_with_standard_start_status,
                component_id="main",
            )
        return oven_with_standard_start_status

    fake_api.async_send_command.side_effect = send_command
    fake_api.async_get_device_status.side_effect = get_status

    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.button.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.advanced_smartthings.button.POSTSTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.button.PRESTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS",
            (),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Bake"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 45},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_target_temperature", "value": 200},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_running"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "samsungce.ovenMode",
            "setOvenMode",
            ["Convection"],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "samsungce.ovenOperatingState",
            "setOperationTime",
            ["00:45:00"],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenSetpoint",
            "setOvenSetpoint",
            [200],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenOperatingState",
            "start",
            ["ConvectionBake", 2700, 200],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_power_switch_uses_warming_start_argument_for_keep_warm_mode(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_with_standard_start = _oven_device_with_standard_start()
    oven_with_standard_start_status = _oven_status_with_standard_start()

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": oven_with_standard_start_status},
    )
    start_calls = 0

    async def send_command(
        device_id: str,
        component_id: str,
        capability: str,
        command: str,
        arguments: list | None = None,
    ) -> dict:
        nonlocal start_calls
        if capability == "ovenOperatingState" and command == "start":
            start_calls += 1
        return {}

    async def get_status(device_id: str) -> dict:
        if start_calls >= 1:
            return _oven_status_with_running_component(
                oven_with_standard_start_status,
                component_id="main",
            )
        return oven_with_standard_start_status

    fake_api.async_send_command.side_effect = send_command
    fake_api.async_get_device_status.side_effect = get_status

    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.button.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.advanced_smartthings.button.POSTSTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.button.PRESTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS",
            (),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Keep Warm"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 30},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_target_temperature", "value": 120},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_running"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenOperatingState",
            "start",
            ["warming", 1800, 120],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_mode_change_restarts_running_oven(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_with_standard_start = _oven_device_with_standard_start()
    running_status = _oven_status_with_running_component(
        _oven_status_with_standard_start(),
        component_id="main",
    )
    running_status["components"]["main"]["samsungce.ovenMode"]["ovenMode"] = {"value": "Convection"}
    running_status["components"]["cavity-01"]["samsungce.ovenMode"]["ovenMode"] = {
        "value": "Convection"
    }
    running_status["components"]["main"]["ovenSetpoint"]["ovenSetpoint"] = {
        "value": 200,
        "unit": "C",
    }
    running_status["components"]["cavity-01"]["ovenSetpoint"]["ovenSetpoint"] = {
        "value": 200,
        "unit": "C",
    }
    running_status["components"]["main"]["samsungce.ovenOperatingState"]["operationTime"] = {
        "value": "00:45:00"
    }
    running_status["components"]["cavity-01"]["samsungce.ovenOperatingState"]["operationTime"] = {
        "value": "00:45:00"
    }

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": running_status},
    )
    start_calls = 0

    async def send_command(
        device_id: str,
        component_id: str,
        capability: str,
        command: str,
        arguments: list | None = None,
    ) -> dict:
        nonlocal start_calls
        if capability == "ovenOperatingState" and command == "start":
            start_calls += 1
        return {}

    async def get_status(device_id: str) -> dict:
        if start_calls >= 1:
            restarted = _oven_status_with_running_component(
                _oven_status_with_standard_start(),
                component_id="main",
            )
            restarted["components"]["main"]["samsungce.ovenMode"]["ovenMode"] = {
                "value": "KeepWarm"
            }
            restarted["components"]["cavity-01"]["samsungce.ovenMode"]["ovenMode"] = {
                "value": "KeepWarm"
            }
            return restarted
        return running_status

    fake_api.async_send_command.side_effect = send_command
    fake_api.async_get_device_status.side_effect = get_status

    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.button.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.advanced_smartthings.button.POSTSTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.button.PRESTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS",
            (),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Keep Warm"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenOperatingState",
            "stop",
            [],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "samsungce.ovenMode",
            "setOvenMode",
            ["KeepWarm"],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenSetpoint",
            "setOvenSetpoint",
            [70],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenOperatingState",
            "start",
            ["warming", 2700, 70],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_power_switch_retries_once_before_succeeding(
    hass,
    mock_config_entry,
    caplog,
) -> None:
    mock_config_entry.add_to_hass(hass)
    caplog.set_level("INFO")

    oven_with_standard_start = _oven_device_with_standard_start()
    oven_with_standard_start_status = _oven_status_with_standard_start()

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": oven_with_standard_start_status},
    )
    start_calls = 0

    async def send_command(
        device_id: str,
        component_id: str,
        capability: str,
        command: str,
        arguments: list | None = None,
    ) -> dict:
        nonlocal start_calls
        if capability == "ovenOperatingState" and command == "start":
            start_calls += 1
        return {"status": "ACCEPTED"}

    async def get_status(device_id: str) -> dict:
        if start_calls >= 2:
            return _oven_status_with_running_component(
                oven_with_standard_start_status,
                component_id="main",
            )
        return oven_with_standard_start_status

    fake_api.async_send_command.side_effect = send_command
    fake_api.async_get_device_status.side_effect = get_status

    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.button.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.advanced_smartthings.button.POSTSTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.button.PRESTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS",
            (),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Bake"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 45},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_target_temperature", "value": 200},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_running"},
            blocking=True,
        )

        start_calls_data = [
            call
            for call in fake_api.async_send_command.await_args_list
            if call.args[2] == "ovenOperatingState" and call.args[3] == "start"
        ]
        assert len(start_calls_data) == 2
        assert '"response_status": "idle_after_start"' in caplog.text
        assert '"response_status": "running"' in caplog.text

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_power_switch_reports_failure_after_retry_when_oven_stays_idle(
    hass,
    mock_config_entry,
    caplog,
) -> None:
    mock_config_entry.add_to_hass(hass)
    caplog.set_level("INFO")

    oven_with_standard_start = _oven_device_with_standard_start()
    oven_with_standard_start_status = _oven_status_with_standard_start()

    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": oven_with_standard_start_status},
    )

    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.button.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.advanced_smartthings.button.POSTSTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.button.PRESTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS",
            (),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Keep Warm"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 30},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_target_temperature", "value": 120},
            blocking=True,
        )

        with pytest.raises(HomeAssistantError, match="remained idle"):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.backofen_running"},
                blocking=True,
            )

        start_calls_data = [
            call
            for call in fake_api.async_send_command.await_args_list
            if call.args[2] == "ovenOperatingState" and call.args[3] == "start"
        ]
        assert len(start_calls_data) == 2
        assert '"mode_argument": "warming"' in caplog.text
        assert '"response_status": "idle_after_retry"' in caplog.text
        assert '"command_path": "standard"' in caplog.text

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_mode_only_exposes_supported_v1_options(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_with_extra_modes = {
        "components": {
            **OVEN_STATUS["components"],
            "cavity-01": {
                **OVEN_STATUS["components"]["cavity-01"],
                "samsungce.ovenMode": {
                    "supportedOvenModes": {
                        "value": ["Convection", "KeepWarm", "AirFry", "Conventional"]
                    },
                    "ovenMode": {"value": "NoOperation"},
                },
            },
        }
    }

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": oven_with_extra_modes},
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        oven_mode = hass.states.get("select.backofen_program")
        assert oven_mode is not None
        assert oven_mode.attributes["options"] == ["Bake", "Keep Warm"]

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Keep Warm"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "cavity-01",
            "samsungce.ovenMode",
            "setOvenMode",
            ["KeepWarm"],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_mode_uses_home_assistant_system_language(
    hass,
    mock_config_entry,
) -> None:
    hass.config.language = "de"
    mock_config_entry.add_to_hass(hass)

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": OVEN_STATUS},
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        oven_mode = hass.states.get("select.backofen_program")
        assert oven_mode is not None
        assert oven_mode.state == "Heißluft"
        assert oven_mode.attributes["options"] == ["Heißluft", "Warmhalten"]
        assert hass.states.get("sensor.backofen_program").state == "Aus"

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Heißluft"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "cavity-01",
            "samsungce.ovenMode",
            "setOvenMode",
            ["Convection"],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_writes_are_blocked_when_remote_control_is_disabled(
    hass,
) -> None:
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Advanced SmartThings",
        data={
            "auth_implementation": "advanced_smartthings-test",
            CONF_CLIENT_ID: CLIENT_ID,
            CONF_CLIENT_SECRET: CLIENT_SECRET,
            CONF_TOKEN: {
                **TOKEN_PAYLOAD,
                "expires_at": 9_999_999_999,
            },
            CONF_LOCATION_IDS: ["location-1"],
        },
        options={CONF_SELECTED_DEVICE_IDS: ["device-oven-1"]},
        unique_id="account-1",
    )
    mock_config_entry.add_to_hass(hass)

    oven_status_remote_disabled = deepcopy(OVEN_STATUS_REMOTE_DISABLED)
    oven_status_remote_disabled["components"]["cavity-01"]["samsungce.ovenMode"]["ovenMode"] = {
        "value": "Convection"
    }

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": oven_status_remote_disabled},
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("binary_sensor.backofen_remote_controllable").state == "off"
        assert hass.states.get("sensor.backofen_program").state == "Bake"
        assert hass.states.get("sensor.backofen_timer").state == "90.0"
        assert hass.states.get("sensor.backofen_target_temperature").state == "180"
        assert hass.states.get("select.backofen_program").state == "unavailable"
        assert hass.states.get("number.backofen_target_temperature").state == "unavailable"
        assert hass.states.get("number.backofen_timer").state == "unavailable"
        assert hass.states.get("switch.backofen_running").state == "unavailable"
        assert hass.states.get("switch.backofen_lamp").state == "off"

        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_lamp"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1", "main", "samsungce.lamp", "setBrightnessLevel", ["high"]
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_power_switch_uses_default_program_while_the_oven_is_off(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_with_standard_start = _oven_device_with_standard_start()
    oven_with_standard_start_status = _oven_status_with_standard_start()
    fake_api = _fake_api(
        [oven_with_standard_start],
        {"device-oven-1": oven_with_standard_start_status},
    )
    start_calls = 0

    async def send_command(
        device_id: str,
        component_id: str,
        capability: str,
        command: str,
        arguments: list | None = None,
    ) -> dict:
        del device_id, arguments
        nonlocal start_calls
        if component_id == "main" and capability == "ovenOperatingState" and command == "start":
            start_calls += 1
        return {}

    async def get_status(device_id: str) -> dict:
        del device_id
        if start_calls >= 1:
            running_status = _oven_status_with_running_component(
                _oven_status_with_standard_start(),
                component_id="main",
            )
            running_status["components"]["main"]["samsungce.ovenMode"]["ovenMode"] = {
                "value": "Convection"
            }
            running_status["components"]["cavity-01"]["samsungce.ovenMode"]["ovenMode"] = {
                "value": "Convection"
            }
            return running_status
        return oven_with_standard_start_status

    fake_api.async_send_command.side_effect = send_command
    fake_api.async_get_device_status.side_effect = get_status

    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.button.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.advanced_smartthings.button.POSTSTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch(
            "custom_components.advanced_smartthings.button.PRESTART_VERIFY_TIMEOUT_SECONDS",
            0.01,
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("select.backofen_program").state == "Bake"

        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 45},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_target_temperature", "value": 200},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_running"},
            blocking=True,
        )

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "main",
            "ovenOperatingState",
            "start",
            ["ConvectionBake", 2700, 200],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_inputs_stay_available_while_the_oven_is_off(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": OVEN_STATUS},
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("select.backofen_program").state == "Bake"
        assert hass.states.get("number.backofen_timer").state == "90.0"
        assert hass.states.get("number.backofen_target_temperature").state == "180.0"
        assert hass.states.get("sensor.backofen_program").state == "Off"
        assert hass.states.get("sensor.backofen_timer").state == "90.0"
        assert hass.states.get("sensor.backofen_target_temperature").state == "180"

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Bake"},
            blocking=True,
        )

        assert hass.states.get("number.backofen_timer").state == "90.0"
        assert hass.states.get("number.backofen_target_temperature").state == "180.0"
        assert hass.states.get("sensor.backofen_program").state == "Bake"

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_writable_entities_send_explicit_commands(
    hass,
) -> None:
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Advanced SmartThings",
        data={
            "auth_implementation": "advanced_smartthings-test",
            CONF_CLIENT_ID: CLIENT_ID,
            CONF_CLIENT_SECRET: CLIENT_SECRET,
            CONF_TOKEN: {
                **TOKEN_PAYLOAD,
                "expires_at": 9_999_999_999,
            },
            CONF_LOCATION_IDS: ["location-1"],
        },
        options={CONF_SELECTED_DEVICE_IDS: ["device-oven-1", "device-fridge-1"]},
        unique_id="account-1",
    )
    mock_config_entry.add_to_hass(hass)

    fake_api = _fake_api(
        [OVEN_DEVICE, FRIDGE_DEVICE],
        {
            "device-oven-1": OVEN_STATUS,
            "device-fridge-1": FRIDGE_STATUS,
        },
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_program", "option": "Bake"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_timer", "value": 45},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.backofen_target_temperature", "value": 200},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_lamp"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.kuhlschrank_refrigerator_temperature", "value": 4},
            blocking=True,
        )

        assert hass.states.get("select.backofen_program").state == "Bake"
        assert hass.states.get("number.backofen_timer").state == "45.0"
        assert hass.states.get("number.backofen_target_temperature").state == "200.0"
        assert hass.states.get("switch.backofen_lamp").state == "on"
        assert hass.states.get("number.kuhlschrank_refrigerator_temperature").state == "4.0"

        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "cavity-01",
            "samsungce.ovenMode",
            "setOvenMode",
            ["Convection"],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "cavity-01",
            "samsungce.ovenOperatingState",
            "setOperationTime",
            ["00:45:00"],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1", "cavity-01", "ovenSetpoint", "setOvenSetpoint", [200]
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1", "main", "samsungce.lamp", "setBrightnessLevel", ["high"]
        )
        fake_api.async_send_command.assert_any_await(
            "device-fridge-1",
            "cooler",
            "thermostatCoolingSetpoint",
            "setCoolingSetpoint",
            [4],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


async def test_oven_power_switch_requires_temperature_before_start(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_without_setpoint = {
        "components": {
            **OVEN_STATUS["components"],
            "cavity-01": {
                **OVEN_STATUS["components"]["cavity-01"],
                "samsungce.ovenMode": {
                    "supportedOvenModes": {"value": ["Convection", "KeepWarm"]},
                    "ovenMode": {"value": "Convection"},
                },
                "samsungce.ovenOperatingState": {
                    "operationTime": {"value": "00:30:00"},
                    "operatingState": {"value": "ready"},
                    "ovenJobState": {"value": "ready"},
                },
                "ovenSetpoint": {
                    "ovenSetpoint": {"value": 0, "unit": "C"},
                },
            },
        }
    }

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {"device-oven-1": oven_without_setpoint},
    )
    with (
        patch(
            "custom_components.advanced_smartthings.async_build_api_client",
            AsyncMock(return_value=fake_api),
        ),
        patch("custom_components.advanced_smartthings.coordinator.POST_COMMAND_REFRESH_DELAYS", ()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        with pytest.raises(HomeAssistantError, match="Set the oven temperature above 0"):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.backofen_running"},
                blocking=True,
            )

        fake_api.async_send_command.assert_not_awaited()

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
