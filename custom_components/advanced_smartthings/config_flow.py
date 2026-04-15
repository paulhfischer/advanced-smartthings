from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import http
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_TOKEN
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv

from .api import async_build_api_client, async_build_preview_api_client
from .const import (
    CONF_LOCATION_IDS,
    CONF_SELECTED_DEVICE_IDS,
    DOMAIN,
    NAME,
    OAUTH_AUTHORIZE_URL,
    OAUTH_SCOPES,
    OAUTH_TOKEN_URL,
)
from .discovery import build_device_catalog, build_device_options, parse_devices
from .exceptions import SmartThingsApiError, SmartThingsConnectionError
from .oauth import SmartThingsOAuth2Implementation

LOGGER = logging.getLogger(__name__)


class AdvancedSmartThingsConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Handle the Advanced SmartThings config flow."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        self._entry_data: dict[str, Any] | None = None
        self._device_options: dict[str, str] = {}
        self._client_credentials: dict[str, str] | None = None

    @property
    def logger(self) -> logging.Logger:
        return LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": " ".join(OAUTH_SCOPES)}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_credentials_schema(),
                description_placeholders={
                    "redirect_uri": _redirect_uri_for_current_request(self.hass)
                },
            )

        self._client_credentials = {
            CONF_CLIENT_ID: user_input[CONF_CLIENT_ID],
            CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
        }
        implementation = self._register_local_implementation(
            user_input[CONF_CLIENT_ID],
            user_input[CONF_CLIENT_SECRET],
        )
        return await self.async_step_pick_implementation({"implementation": implementation.domain})

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={
                    "redirect_uri": _redirect_uri_for_current_request(self.hass)
                },
            )
        reauth_entry = self._get_reauth_entry()
        self._client_credentials = {
            CONF_CLIENT_ID: str(reauth_entry.data[CONF_CLIENT_ID]),
            CONF_CLIENT_SECRET: str(reauth_entry.data[CONF_CLIENT_SECRET]),
        }
        implementation = self._register_local_implementation(
            self._client_credentials[CONF_CLIENT_ID],
            self._client_credentials[CONF_CLIENT_SECRET],
        )
        return await self.async_step_pick_implementation({"implementation": implementation.domain})

    async def async_step_select_devices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if self._entry_data is None:
            return self.async_abort(reason="missing_oauth_state")

        if user_input is not None:
            selected_device_ids = user_input[CONF_SELECTED_DEVICE_IDS]
            if not selected_device_ids:
                return self.async_show_form(
                    step_id="select_devices",
                    data_schema=_selection_schema(self._device_options),
                    errors={"base": "no_devices_selected"},
                )
            return self.async_create_entry(
                title=NAME,
                data=self._entry_data,
                options={CONF_SELECTED_DEVICE_IDS: list(selected_device_ids)},
            )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=_selection_schema(self._device_options),
        )

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        if not _token_has_required_scopes(data):
            return self.async_abort(reason="missing_scopes")

        api = async_build_preview_api_client(self.hass, data[CONF_TOKEN])
        try:
            locations = await api.async_get_locations()
            devices = parse_devices(await api.async_get_devices())
            capability_definitions = await api.async_prefetch_capability_definitions(
                {
                    (capability.capability_id, capability.capability_version)
                    for device in devices
                    for capability in device.capabilities
                }
            )
        except SmartThingsConnectionError:
            return self.async_abort(reason="cannot_connect")
        except SmartThingsApiError:
            LOGGER.exception("SmartThings OAuth succeeded but device discovery failed")
            return self.async_abort(reason="api_error")

        location_ids = sorted(
            location["locationId"]
            for location in locations
            if isinstance(location.get("locationId"), str)
        )
        if not location_ids:
            return self.async_abort(reason="no_locations_found")

        await self.async_set_unique_id(_account_unique_id(location_ids))
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="reauth_account_mismatch")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates={
                    **data,
                    CONF_LOCATION_IDS: location_ids,
                },
            )

        self._abort_if_unique_id_configured()

        catalog = build_device_catalog(devices, capability_definitions=capability_definitions)
        device_options = build_device_options(catalog)
        if not device_options:
            return self.async_abort(reason="no_supported_devices")

        self._entry_data = {
            **data,
            **(self._client_credentials or {}),
            CONF_LOCATION_IDS: location_ids,
        }
        self._device_options = device_options
        return await self.async_step_select_devices()

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> AdvancedSmartThingsOptionsFlow:
        return AdvancedSmartThingsOptionsFlow(config_entry)

    def _register_local_implementation(
        self,
        client_id: str,
        client_secret: str,
    ) -> SmartThingsOAuth2Implementation:
        implementation = SmartThingsOAuth2Implementation(
            self.hass,
            _implementation_id(self.flow_id),
            client_id,
            client_secret,
            OAUTH_AUTHORIZE_URL,
            OAUTH_TOKEN_URL,
        )
        config_entry_oauth2_flow.async_register_implementation(self.hass, DOMAIN, implementation)
        return implementation


class AdvancedSmartThingsOptionsFlow(OptionsFlow):
    """Handle the Advanced SmartThings options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._device_options: dict[str, str] = {}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if not self._device_options:
            try:
                api = await async_build_api_client(self.hass, self._config_entry)
                devices = parse_devices(await api.async_get_devices())
                capability_definitions = await api.async_prefetch_capability_definitions(
                    {
                        (capability.capability_id, capability.capability_version)
                        for device in devices
                        for capability in device.capabilities
                    }
                )
            except SmartThingsConnectionError:
                return self.async_abort(reason="cannot_connect")
            except SmartThingsApiError:
                LOGGER.exception("SmartThings options flow failed to load devices")
                return self.async_abort(reason="api_error")

            self._device_options = build_device_options(
                build_device_catalog(devices, capability_definitions)
            )

        if user_input is not None:
            selected_device_ids = user_input[CONF_SELECTED_DEVICE_IDS]
            if not selected_device_ids:
                return self.async_show_form(
                    step_id="init",
                    data_schema=_selection_schema(
                        self._device_options,
                        default=list(self._config_entry.options.get(CONF_SELECTED_DEVICE_IDS, [])),
                    ),
                    errors={"base": "no_devices_selected"},
                )
            return self.async_create_entry(
                title="",
                data={CONF_SELECTED_DEVICE_IDS: list(selected_device_ids)},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_selection_schema(
                self._device_options,
                default=list(self._config_entry.options.get(CONF_SELECTED_DEVICE_IDS, [])),
            ),
        )


def _selection_schema(options: dict[str, str], default: list[str] | None = None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_DEVICE_IDS, default=default or []): cv.multi_select(options),
        }
    )


def _credentials_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CLIENT_ID): str,
            vol.Required(CONF_CLIENT_SECRET): str,
        }
    )


def _token_has_required_scopes(data: dict[str, Any]) -> bool:
    token = data.get(CONF_TOKEN)
    if not isinstance(token, dict):
        return False
    scope = token.get("scope")
    if not isinstance(scope, str):
        return False
    granted = {token_scope for token_scope in scope.split() if token_scope}
    return set(OAUTH_SCOPES) <= granted


def _account_unique_id(location_ids: list[str]) -> str:
    joined = ",".join(location_ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _implementation_id(flow_id: str) -> str:
    return f"{DOMAIN}-{flow_id}"


def _redirect_uri_for_current_request(hass) -> str:
    if "my" in hass.config.components:
        return config_entry_oauth2_flow.MY_AUTH_CALLBACK_PATH

    if (req := http.current_request.get()) is None:
        return config_entry_oauth2_flow.AUTH_CALLBACK_PATH

    if (ha_host := req.headers.get(config_entry_oauth2_flow.HEADER_FRONTEND_BASE)) is None:
        return config_entry_oauth2_flow.AUTH_CALLBACK_PATH

    return f"{ha_host}{config_entry_oauth2_flow.AUTH_CALLBACK_PATH}"
