from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import UTC
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from .errors import InvalidOAuthStateError
from .errors import TokenRefreshError
from .errors import UpstreamRequestError
from .errors import UpstreamTimeoutError
from .models import PendingOAuthState
from .models import TokenBundle
from .settings import ServiceSettings


class OAuthManager:
    def __init__(self, settings: ServiceSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client

    def create_pending_state(self, callback_url: str) -> PendingOAuthState:
        now = datetime.now(UTC)
        return PendingOAuthState(
            value=secrets.token_urlsafe(32),
            callback_url=callback_url,
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.oauth_state_ttl_seconds),
        )

    def build_authorization_url(self, pending_state: PendingOAuthState) -> str:
        if not self._settings.smartthings_client_id:
            raise UpstreamRequestError("SmartThings client ID is not configured.")

        query = urlencode(
            {
                "client_id": self._settings.smartthings_client_id,
                "response_type": "code",
                "redirect_uri": pending_state.callback_url,
                "scope": self._settings.oauth_scope,
                "state": pending_state.value,
            }
        )
        return f"{self._settings.oauth_authorize_url}?{query}"

    def validate_state(self, pending_state: PendingOAuthState | None, supplied_state: str) -> None:
        if pending_state is None:
            raise InvalidOAuthStateError("No OAuth state is pending.")
        if pending_state.expires_at <= datetime.now(UTC):
            raise InvalidOAuthStateError("The pending OAuth state has expired.")
        if pending_state.value != supplied_state:
            raise InvalidOAuthStateError("The supplied OAuth state does not match the stored state.")

    async def exchange_code(self, code: str, callback_url: str) -> TokenBundle:
        return await self._request_token(
            grant_type="authorization_code",
            payload={"code": code, "redirect_uri": callback_url},
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenBundle:
        try:
            return await self._request_token(
                grant_type="refresh_token",
                payload={"refresh_token": refresh_token},
                fallback_refresh_token=refresh_token,
            )
        except UpstreamRequestError as err:
            raise TokenRefreshError(message=err.message) from err
        except UpstreamTimeoutError as err:
            raise TokenRefreshError(message=err.message) from err

    async def _request_token(
        self,
        grant_type: str,
        payload: dict[str, Any],
        fallback_refresh_token: str | None = None,
    ) -> TokenBundle:
        client_secret = self._settings.smartthings_client_secret
        if not self._settings.smartthings_client_id or client_secret is None:
            raise UpstreamRequestError("SmartThings OAuth credentials are not configured.")

        data = {
            "grant_type": grant_type,
            "client_id": self._settings.smartthings_client_id,
            **payload,
        }

        try:
            response = await self._http_client.post(
                self._settings.oauth_token_url,
                data=data,
                auth=(self._settings.smartthings_client_id, client_secret.get_secret_value()),
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as err:
            raise UpstreamTimeoutError("Timed out while contacting SmartThings OAuth.") from err
        except httpx.HTTPError as err:
            raise UpstreamRequestError(
                message="Unable to reach SmartThings OAuth.",
                details={"error": str(err)},
            ) from err

        if response.status_code >= 400:
            raise UpstreamRequestError(
                message="SmartThings OAuth rejected the token request.",
                details={"status_code": response.status_code, "body": _sanitize_body(response)},
            )

        try:
            data = response.json()
        except ValueError as err:
            raise UpstreamRequestError(
                message="SmartThings OAuth returned invalid JSON.",
                details={"status_code": response.status_code},
            ) from err

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token", fallback_refresh_token)
        expires_in = data.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise UpstreamRequestError("SmartThings OAuth response did not contain an access token.")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise UpstreamRequestError("SmartThings OAuth response did not contain a refresh token.")
        if not isinstance(expires_in, int):
            raise UpstreamRequestError("SmartThings OAuth response did not contain expires_in.")

        return TokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            scope=data.get("scope"),
            token_type=str(data.get("token_type", "Bearer")),
        )


def _sanitize_body(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"text": response.text[:200]}

    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            if "token" in key.lower() or "secret" in key.lower():
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        return sanitized
    return {"value": str(payload)[:200]}
