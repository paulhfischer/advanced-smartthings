from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow

from custom_components.advanced_smartthings.const import (
    CONF_SELECTED_DEVICE_IDS,
    DOMAIN,
    OAUTH_AUTHORIZE_URL,
)

from .conftest import (
    COOKTOP_DEVICE,
    FRIDGE_DEVICE,
    LOCATIONS_PAYLOAD,
    OVEN_DEVICE,
    OVEN_SETPOINT_DEFINITION,
    SAMSUNG_OVEN_MODE_DEFINITION,
    THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    TOKEN_PAYLOAD,
    UNSUPPORTED_DEVICE,
)


@pytest.mark.usefixtures("current_request_with_host")
async def test_full_flow_prompts_for_device_selection(
    hass,
    mock_setup_entry,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {
        "redirect_uri": "https://example.com/auth/external/callback"
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        },
    )

    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": "https://example.com/auth/external/callback",
        },
    )

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith(
        f"{OAUTH_AUTHORIZE_URL}?response_type=code&client_id=test-client-id"
    )
    assert "&scope=r:devices:*+x:devices:*+r:locations:*" in result["url"]
    assert f"&state={state}" in result["url"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "state": {
                "flow_id": result["flow_id"],
                "redirect_uri": "https://example.com/auth/external/callback",
            },
            "code": "auth-code",
        },
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE

    preview_api = AsyncMock()
    preview_api.async_get_locations.return_value = LOCATIONS_PAYLOAD["items"]
    preview_api.async_get_devices.return_value = [
        OVEN_DEVICE,
        FRIDGE_DEVICE,
        COOKTOP_DEVICE,
        UNSUPPORTED_DEVICE,
    ]
    preview_api.async_prefetch_capability_definitions.return_value = {
        ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
        ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
        ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    }

    with (
        patch(
            "custom_components.advanced_smartthings.oauth.SmartThingsOAuth2Implementation.async_resolve_external_data",
            AsyncMock(return_value=TOKEN_PAYLOAD),
        ),
        patch(
            "custom_components.advanced_smartthings.config_flow.async_build_preview_api_client",
            return_value=preview_api,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_devices"

    with patch.object(hass.config_entries, "async_setup", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_SELECTED_DEVICE_IDS: ["device-oven-1", "device-fridge-1", "device-cooktop-1"]
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Advanced SmartThings"
    assert result["options"] == {
        CONF_SELECTED_DEVICE_IDS: ["device-oven-1", "device-fridge-1", "device-cooktop-1"]
    }


@pytest.mark.usefixtures("current_request_with_host")
async def test_flow_aborts_when_scopes_are_missing(
    hass,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["description_placeholders"] == {
        "redirect_uri": "https://example.com/auth/external/callback"
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "state": {
                "flow_id": result["flow_id"],
                "redirect_uri": "https://example.com/auth/external/callback",
            },
            "code": "auth-code",
        },
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE

    with patch(
        "custom_components.advanced_smartthings.oauth.SmartThingsOAuth2Implementation.async_resolve_external_data",
        AsyncMock(
            return_value={
                "access_token": "abc",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": "r:devices:* x:devices:*",
            }
        ),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "missing_scopes"
