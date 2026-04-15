from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .const import API_BASE_URL, OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL
from .exceptions import SmartThingsApiError, SmartThingsConnectionError
from .oauth import SmartThingsOAuth2Implementation

LOGGER = logging.getLogger(__name__)
AccessTokenProvider = Callable[[], Awaitable[str]]


class SmartThingsApiClient:
    """Thin SmartThings REST client backed by Home Assistant OAuth2Session."""

    def __init__(
        self, websession: ClientSession, access_token_provider: AccessTokenProvider
    ) -> None:
        self._websession = websession
        self._access_token_provider = access_token_provider
        self._capability_definition_cache: dict[tuple[str, int], dict[str, Any] | None] = {}

    async def async_get_locations(self) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", "/locations")
        return _extract_items(payload, "locations")

    async def async_get_devices(self) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", "/devices")
        return _extract_items(payload, "devices")

    async def async_get_device_status(self, device_id: str) -> dict[str, Any]:
        return await self._request_json("GET", f"/devices/{quote(device_id, safe='')}/status")

    async def async_get_capability_definition(
        self,
        capability_id: str,
        version: int = 1,
    ) -> dict[str, Any] | None:
        cache_key = (capability_id, version)
        if cache_key in self._capability_definition_cache:
            return self._capability_definition_cache[cache_key]

        try:
            definition = await self._request_json(
                "GET",
                f"/capabilities/{quote(capability_id, safe='')}/{version}",
            )
        except SmartThingsApiError:
            definition = None

        self._capability_definition_cache[cache_key] = definition
        return definition

    async def async_prefetch_capability_definitions(
        self,
        capabilities: Iterable[tuple[str, int]],
    ) -> dict[tuple[str, int], dict[str, Any] | None]:
        return {
            (capability_id, version): await self.async_get_capability_definition(
                capability_id, version
            )
            for capability_id, version in capabilities
        }

    async def async_send_command(
        self,
        device_id: str,
        component_id: str,
        capability: str,
        command: str,
        arguments: list[Any] | None = None,
    ) -> dict[str, Any]:
        return await self.async_send_commands(
            device_id,
            [
                {
                    "component": component_id,
                    "capability": capability,
                    "command": command,
                    "arguments": arguments or [],
                }
            ],
        )

    async def async_send_commands(
        self,
        device_id: str,
        commands: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {"commands": commands}
        return await self._request_json(
            "POST", f"/devices/{quote(device_id, safe='')}/commands", json_data=payload
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._access_token_provider()
        if not token:
            raise ConfigEntryAuthFailed("SmartThings token is missing an access token")

        try:
            response = await self._websession.request(
                method,
                f"{API_BASE_URL}{path}",
                json=json_data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except ClientError as err:
            raise SmartThingsConnectionError("Unable to reach SmartThings.") from err

        if response.status == 401:
            raise ConfigEntryAuthFailed("SmartThings rejected the current access token")
        if response.status >= 400:
            error_body = await _read_json_or_text(response)
            raise SmartThingsApiError(
                f"SmartThings request failed with status {response.status}: {error_body}"
            )

        payload = await response.json()
        if not isinstance(payload, dict):
            raise SmartThingsApiError("SmartThings returned a non-object JSON response")

        LOGGER.debug("SmartThings request succeeded: method=%s path=%s", method, path)
        return payload


async def async_build_api_client(hass: HomeAssistant, entry: ConfigEntry) -> SmartThingsApiClient:
    """Create a SmartThings API client for a config entry."""
    client_id = entry.data.get(CONF_CLIENT_ID)
    client_secret = entry.data.get(CONF_CLIENT_SECRET)
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise ConfigEntryAuthFailed(
            "SmartThings client credentials are missing from the config entry"
        )

    implementation = SmartThingsOAuth2Implementation(
        hass,
        entry.data.get("auth_implementation", entry.entry_id),
        client_id,
        client_secret,
        OAUTH_AUTHORIZE_URL,
        OAUTH_TOKEN_URL,
    )
    oauth_session = OAuth2Session(hass, entry, implementation)
    websession = async_get_clientsession(hass)
    return SmartThingsApiClient(websession, _oauth_access_token_provider(oauth_session))


def async_build_preview_api_client(
    hass: HomeAssistant, token_data: dict[str, Any]
) -> SmartThingsApiClient:
    """Create a SmartThings API client directly from OAuth token payload."""
    websession = async_get_clientsession(hass)
    return SmartThingsApiClient(websession, _preview_access_token_provider(token_data))


def _extract_items(payload: dict[str, Any], resource_name: str) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise SmartThingsApiError(
            f"SmartThings {resource_name} response did not contain an items array"
        )
    return [item for item in items if isinstance(item, dict)]


async def _read_json_or_text(response) -> str:
    try:
        payload = await response.json()
    except (ClientError, ValueError):
        payload = await response.text()

    if isinstance(payload, dict):
        return str(
            {key: ("***" if "token" in key.casefold() else value) for key, value in payload.items()}
        )
    return str(payload)[:200]


def _oauth_access_token_provider(oauth_session: OAuth2Session) -> AccessTokenProvider:
    async def provider() -> str:
        await oauth_session.async_ensure_token_valid()
        token = oauth_session.token.get(CONF_ACCESS_TOKEN)
        if not isinstance(token, str) or not token:
            raise ConfigEntryAuthFailed("SmartThings token is missing an access token")
        return token

    return provider


def _preview_access_token_provider(token_data: dict[str, Any]) -> AccessTokenProvider:
    async def provider() -> str:
        token = token_data.get(CONF_ACCESS_TOKEN)
        if not isinstance(token, str) or not token:
            raise ConfigEntryAuthFailed("SmartThings token is missing an access token")
        return token

    return provider
