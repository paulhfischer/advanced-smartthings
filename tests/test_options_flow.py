from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.advanced_smartthings.const import CONF_SELECTED_DEVICE_IDS

from .conftest import (
    COOKTOP_DEVICE,
    FRIDGE_DEVICE,
    OVEN_DEVICE,
    OVEN_SETPOINT_DEFINITION,
    SAMSUNG_OVEN_MODE_DEFINITION,
    THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    UNSUPPORTED_DEVICE,
)


async def test_options_flow_updates_selected_devices(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)

    fake_api = AsyncMock()
    fake_api.async_get_devices.return_value = [
        OVEN_DEVICE,
        FRIDGE_DEVICE,
        COOKTOP_DEVICE,
        UNSUPPORTED_DEVICE,
    ]
    fake_api.async_prefetch_capability_definitions.return_value = {
        ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
        ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
        ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    }

    with patch(
        "custom_components.advanced_smartthings.config_flow.async_build_api_client",
        AsyncMock(return_value=fake_api),
    ):
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_SELECTED_DEVICE_IDS: ["device-fridge-1"]},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SELECTED_DEVICE_IDS: ["device-fridge-1"]}
