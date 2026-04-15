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
        fake_api.async_send_command.assert_any_await(
            "device-fridge-1",
            "cooler",
            "thermostatCoolingSetpoint",
            "setCoolingSetpoint",
            [4],
        )

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
