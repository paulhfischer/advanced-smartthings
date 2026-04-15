from __future__ import annotations

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
    api.async_prefetch_capability_definitions.return_value = {
        ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
        ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
        ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    }

    async def get_status(device_id: str) -> dict:
        return status_by_device[device_id]

    api.async_get_device_status.side_effect = get_status
    return api


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

        assert hass.states.get("select.backofen_oven_mode").state == "Off"
        assert hass.states.get("binary_sensor.backofen_remote_control").state == "on"
        assert (
            hass.states.get("select.backofen_oven_mode").attributes["remote_control_enabled"]
            is True
        )
        assert hass.states.get("button.backofen_start_program") is not None
        assert hass.states.get("button.backofen_stop_program") is not None
        assert hass.states.get("number.backofen_timer").state == "90.0"
        assert hass.states.get("number.backofen_temperature").state == "180.0"
        assert hass.states.get("switch.backofen_lamp").state == "off"

        assert hass.states.get("binary_sensor.kuhlschrank_refrigerator_door").state == "off"
        assert hass.states.get("binary_sensor.kuhlschrank_freezer_door").state == "on"
        assert hass.states.get("number.kuhlschrank_refrigerator_temperature").state == "6.0"
        assert hass.states.get("number.kuhlschrank_freezer_temperature").state == "-18.0"
        assert hass.states.get("sensor.kuhlschrank_power_consumption").state == "1458"
        assert hass.states.get("sensor.kuhlschrank_water_filter_usage").state == "13"

        assert hass.states.get("binary_sensor.kochfeld_cooktop_active").state == "off"

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
        {
            "device-oven-1": oven_without_timer_spec,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

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


async def test_oven_start_button_uses_standard_start_when_device_supports_it(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    oven_with_standard_start = {
        **OVEN_DEVICE,
        "components": [
            {
                **OVEN_DEVICE["components"][0],
                "capabilities": [
                    *OVEN_DEVICE["components"][0]["capabilities"],
                    {"id": "ovenMode", "version": 1},
                    {"id": "ovenOperatingState", "version": 1},
                    {"id": "ovenSetpoint", "version": 1},
                ],
            },
            {
                **OVEN_DEVICE["components"][1],
                "capabilities": [
                    *OVEN_DEVICE["components"][1]["capabilities"],
                    {"id": "ovenMode", "version": 1},
                    {"id": "ovenOperatingState", "version": 1},
                ],
            },
        ],
    }
    oven_with_standard_start_status = {
        "components": {
            **OVEN_STATUS["components"],
            "main": {
                **OVEN_STATUS["components"]["main"],
                "ovenMode": {
                    "supportedOvenModes": {"value": ["Others", "ConvectionBake", "Conventional"]},
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
                "ovenMode": {
                    "supportedOvenModes": {"value": ["Others", "Bake"]},
                    "ovenMode": {"value": "Others"},
                },
                "ovenOperatingState": {
                    "operationTime": {"value": 0},
                    "machineState": {"value": "ready"},
                    "progress": {"value": 0, "unit": "%"},
                    "ovenJobState": {"value": "ready"},
                },
            },
        }
    }

    fake_api = _fake_api(
        [oven_with_standard_start],
        {
            "device-oven-1": oven_with_standard_start_status,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_oven_mode", "option": "Convection"},
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
            {"entity_id": "number.backofen_temperature", "value": 200},
            blocking=True,
        )
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.backofen_start_program"},
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


async def test_oven_mode_uses_home_assistant_system_language(
    hass,
    mock_config_entry,
) -> None:
    hass.config.language = "de"
    mock_config_entry.add_to_hass(hass)

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {
            "device-oven-1": OVEN_STATUS,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        oven_mode = hass.states.get("select.backofen_backmodus")
        assert oven_mode is not None
        assert oven_mode.state == "Aus"
        assert "Umluft" in oven_mode.attributes["options"]

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_backmodus", "option": "Umluft"},
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

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {
            "device-oven-1": OVEN_STATUS_REMOTE_DISABLED,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("binary_sensor.backofen_remote_control").state == "off"
        assert (
            hass.states.get("number.backofen_temperature").attributes["remote_control_enabled"]
            is False
        )

        with pytest.raises(HomeAssistantError, match="Remote control is disabled"):
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": "select.backofen_oven_mode", "option": "Convection"},
                blocking=True,
            )

        with pytest.raises(HomeAssistantError, match="Remote control is disabled"):
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": "number.backofen_temperature", "value": 200},
                blocking=True,
            )

        with pytest.raises(HomeAssistantError, match="Remote control is disabled"):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.backofen_start_program"},
                blocking=True,
            )

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


async def test_oven_start_button_requires_selected_mode(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {
            "device-oven-1": OVEN_STATUS,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        with pytest.raises(HomeAssistantError, match="Select an oven mode"):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.backofen_start_program"},
                blocking=True,
            )

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
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.backofen_oven_mode", "option": "Convection"},
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
            {"entity_id": "number.backofen_temperature", "value": 200},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.backofen_lamp"},
            blocking=True,
        )
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.backofen_start_program"},
            blocking=True,
        )
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.backofen_stop_program"},
            blocking=True,
        )
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.kuhlschrank_refrigerator_temperature", "value": 4},
            blocking=True,
        )

        assert hass.states.get("select.backofen_oven_mode").state == "Convection"
        assert hass.states.get("number.backofen_timer").state == "45.0"
        assert hass.states.get("number.backofen_temperature").state == "200.0"
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
        fake_api.async_send_commands.assert_any_await(
            "device-oven-1",
            [
                {
                    "component": "cavity-01",
                    "capability": "samsungce.ovenMode",
                    "command": "setOvenMode",
                    "arguments": ["Convection"],
                },
                {
                    "component": "cavity-01",
                    "capability": "ovenSetpoint",
                    "command": "setOvenSetpoint",
                    "arguments": [200],
                },
                {
                    "component": "cavity-01",
                    "capability": "samsungce.ovenOperatingState",
                    "command": "setOperationTime",
                    "arguments": ["00:45:00"],
                },
                {
                    "component": "cavity-01",
                    "capability": "samsungce.ovenOperatingState",
                    "command": "start",
                    "arguments": [],
                },
            ],
        )
        fake_api.async_send_command.assert_any_await(
            "device-oven-1",
            "cavity-01",
            "samsungce.ovenOperatingState",
            "stop",
            [],
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


async def test_oven_start_button_uses_mode_default_temperature_when_missing(
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
                    "supportedOvenModes": {"value": ["Convection", "Conventional"]},
                    "ovenMode": {"value": "Convection"},
                },
                "samsungce.ovenOperatingState": {
                    "operationTime": {"value": "00:00:00"},
                },
                "ovenSetpoint": {
                    "ovenSetpoint": {"value": 0, "unit": "C"},
                },
            },
        }
    }

    fake_api = _fake_api(
        [OVEN_DEVICE],
        {
            "device-oven-1": oven_without_setpoint,
        },
    )
    with patch(
        "custom_components.advanced_smartthings.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.backofen_start_program"},
            blocking=True,
        )

        fake_api.async_send_commands.assert_any_await(
            "device-oven-1",
            [
                {
                    "component": "cavity-01",
                    "capability": "samsungce.ovenMode",
                    "command": "setOvenMode",
                    "arguments": ["Convection"],
                },
                {
                    "component": "cavity-01",
                    "capability": "ovenSetpoint",
                    "command": "setOvenSetpoint",
                    "arguments": [160],
                },
                {
                    "component": "cavity-01",
                    "capability": "samsungce.ovenOperatingState",
                    "command": "start",
                    "arguments": [],
                },
            ],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
