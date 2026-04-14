"""Local OAuth implementation for Advanced SmartThings."""

from __future__ import annotations

import base64
from typing import Any

from aiohttp import ClientError
from homeassistant.const import CONF_CLIENT_ID
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession


class SmartThingsOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation that sends SmartThings token requests via HTTP Basic auth."""

    async def _token_request(self, data: dict[str, Any]) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)

        payload = {
            CONF_CLIENT_ID: self.client_id,
            **data,
        }

        try:
            response = await session.post(
                self.token_url,
                data=payload,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Basic {self._basic_auth_token}",
                },
            )
        except ClientError as err:
            raise config_entry_oauth2_flow.OAuth2TokenRequestError(
                "Unable to reach SmartThings OAuth."
            ) from err

        if response.status >= 400:
            error_body = await response.text()
            raise config_entry_oauth2_flow.OAuth2TokenRequestError(
                "SmartThings OAuth rejected the token request: "
                f"{response.status} {error_body[:200]}"
            )

        payload = await response.json()
        if not isinstance(payload, dict):
            raise config_entry_oauth2_flow.OAuth2TokenRequestError(
                "SmartThings OAuth returned a non-object JSON response."
            )
        return payload

    @property
    def _basic_auth_token(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return base64.b64encode(raw).decode()
