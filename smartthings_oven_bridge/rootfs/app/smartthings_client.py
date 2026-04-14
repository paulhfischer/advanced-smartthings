from __future__ import annotations

from collections.abc import Awaitable
from collections.abc import Callable
import logging
from typing import Any

import httpx

from .errors import AuthenticationRequiredError
from .errors import ConfigurationError
from .errors import UnsupportedCapabilityError
from .errors import UpstreamNotFoundError
from .errors import UpstreamPermissionError
from .errors import UpstreamRequestError
from .errors import UpstreamTimeoutError
from .models import DeviceCommand
from .models import StartWarmingRequest
from .settings import ServiceSettings


AccessTokenProvider = Callable[[bool], Awaitable[str]]
AsyncCallback = Callable[[], Awaitable[None]]
AsyncReasonCallback = Callable[[str], Awaitable[None]]


class SmartThingsClient:
    def __init__(
        self,
        settings: ServiceSettings,
        http_client: httpx.AsyncClient,
        access_token_provider: AccessTokenProvider,
        mark_contact_success: AsyncCallback,
        mark_auth_broken: AsyncReasonCallback,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._access_token_provider = access_token_provider
        self._mark_contact_success = mark_contact_success
        self._mark_auth_broken = mark_auth_broken
        self._logger = logger or logging.getLogger(__name__)

    async def get_device(self) -> dict[str, Any]:
        response = await self._request("GET", f"/devices/{self._device_id}")
        return response.json()

    async def get_device_status(self) -> dict[str, Any]:
        response = await self._request("GET", f"/devices/{self._device_id}/status")
        return response.json()

    async def list_devices(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/devices")
        payload = response.json()
        if not isinstance(payload, dict):
            raise UpstreamRequestError("SmartThings device list response was not an object.")

        items = payload.get("items", [])
        if not isinstance(items, list):
            raise UpstreamRequestError("SmartThings device list response did not contain an items array.")
        return [item for item in items if isinstance(item, dict)]

    async def send_device_commands(self, commands: list[DeviceCommand]) -> None:
        payload = {"commands": [command.model_dump() for command in commands]}
        await self._request("POST", f"/devices/{self._device_id}/commands", json=payload)

    def build_stop_commands(
        self,
        device: dict[str, Any],
        status: dict[str, Any] | None,
    ) -> list[DeviceCommand]:
        capabilities = _capabilities_for(device, status)
        for capability, command, arguments in (
            ("switch", "off", []),
            ("ovenOperatingState", "stop", []),
            ("samsungce.ovenOperatingState", "stop", []),
            ("ovenMode", "setOvenMode", ["off"]),
            ("samsungce.ovenMode", "setOvenMode", ["off"]),
        ):
            if capability in capabilities:
                return [DeviceCommand(capability=capability, command=command, arguments=arguments)]

        raise UnsupportedCapabilityError(
            details={"available_capabilities": sorted(capabilities)},
        )

    def build_start_warming_commands(
        self,
        request: StartWarmingRequest,
        device: dict[str, Any],
        status: dict[str, Any] | None,
    ) -> tuple[list[DeviceCommand], bool]:
        capabilities = _capabilities_for(device, status)
        commands: list[DeviceCommand] = []
        duration_applied = False

        mode_command = _first_matching_command(
            capabilities,
            (
                ("ovenMode", "setOvenMode", ["warming"]),
                ("samsungce.ovenMode", "setOvenMode", ["warming"]),
                ("thermostatMode", "setThermostatMode", ["heat"]),
            ),
        )
        if mode_command is None:
            raise UnsupportedCapabilityError(
                message="No supported warming-mode capability was found for this device.",
                details={"available_capabilities": sorted(capabilities)},
            )
        commands.append(mode_command)

        setpoint_command = _first_matching_command(
            capabilities,
            (
                ("ovenSetpoint", "setOvenSetpoint", [request.setpoint]),
                ("temperatureControlSetpoint", "setHeatingSetpoint", [request.setpoint]),
                ("thermostatHeatingSetpoint", "setHeatingSetpoint", [request.setpoint]),
            ),
        )
        if setpoint_command is not None:
            commands.append(setpoint_command)

        duration_command = _first_matching_command(
            capabilities,
            (
                ("cookTime", "setCookTime", [request.duration_seconds]),
                ("custom.cookTime", "setCookTime", [request.duration_seconds]),
                ("ovenCavityOperation", "setOperationTime", [request.duration_seconds]),
            ),
        )
        if duration_command is not None:
            commands.append(duration_command)
            duration_applied = True

        return commands, duration_applied

    def is_likely_stopped(self, status: dict[str, Any] | None) -> bool:
        if not status:
            return False

        for raw_value in _status_values(status):
            if raw_value in {"off", "stopped", "idle", "ready", "complete", "completed"}:
                return True
            if raw_value in {"heating", "cooking", "warming", "on", "running"}:
                return False
        return False

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        retry_on_unauthorized: bool = True,
    ) -> httpx.Response:
        token = await self._access_token_provider(False)
        response = await self._send(method, path, token=token, json=json)

        if response.status_code == 401 and retry_on_unauthorized:
            token = await self._access_token_provider(True)
            response = await self._send(method, path, token=token, json=json)
            if response.status_code == 401:
                await self._mark_auth_broken("unauthorized_after_refresh")
                raise AuthenticationRequiredError("SmartThings authorization is invalid after a forced token refresh.")

        if response.status_code == 403:
            raise UpstreamPermissionError
        if response.status_code == 404:
            raise UpstreamNotFoundError
        if response.status_code >= 400:
            raise UpstreamRequestError(
                details={
                    "status_code": response.status_code,
                    "body": _sanitize_upstream_body(response),
                    "path": path,
                }
            )

        await self._mark_contact_success()
        return response

    async def _send(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json: dict[str, Any] | None,
    ) -> httpx.Response:
        try:
            response = await self._http_client.request(
                method,
                f"{self._settings.smartthings_api_base_url.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=json,
            )
        except httpx.TimeoutException as err:
            raise UpstreamTimeoutError from err
        except httpx.HTTPError as err:
            raise UpstreamRequestError(
                details={"error": str(err), "path": path},
            ) from err

        self._logger.info(
            "event=smartthings_request status_code=%s method=%s path=%s",
            response.status_code,
            method,
            path,
        )
        return response

    @property
    def _device_id(self) -> str:
        if not self._settings.smartthings_device_id:
            raise ConfigurationError("A SmartThings device ID is required.")
        return self._settings.smartthings_device_id


def _first_matching_command(
    capabilities: set[str],
    candidates: tuple[tuple[str, str, list[Any]], ...],
) -> DeviceCommand | None:
    for capability, command, arguments in candidates:
        if capability in capabilities:
            return DeviceCommand(capability=capability, command=command, arguments=arguments)
    return None


def _capabilities_for(device: dict[str, Any], status: dict[str, Any] | None) -> set[str]:
    discovered: set[str] = set()
    for component in device.get("components", []):
        if component.get("id") != "main":
            continue
        for capability in component.get("capabilities", []):
            if isinstance(capability, str):
                discovered.add(capability)
            elif isinstance(capability, dict):
                identifier = capability.get("id")
                if isinstance(identifier, str):
                    discovered.add(identifier)

    components = (status or {}).get("components", {})
    main = components.get("main", {})
    if isinstance(main, dict):
        discovered.update(main.keys())
    return discovered


def _status_values(status: dict[str, Any]) -> list[str]:
    values: list[str] = []
    main = status.get("components", {}).get("main", {})
    if not isinstance(main, dict):
        return values

    for capability_payload in main.values():
        if not isinstance(capability_payload, dict):
            continue
        for attribute in capability_payload.values():
            if not isinstance(attribute, dict):
                continue
            raw_value = attribute.get("value")
            if isinstance(raw_value, str):
                values.append(raw_value.lower())
    return values


def _sanitize_upstream_body(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"text": response.text[:200]}

    if isinstance(payload, dict):
        return payload
    return {"value": str(payload)[:200]}
