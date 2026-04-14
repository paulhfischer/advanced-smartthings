from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import UTC
import hashlib
import json
import logging
from typing import Any
from urllib.parse import urljoin

from fastapi import Request
import httpx

from .errors import AuthenticationRequiredError
from .errors import BridgeError
from .errors import ConfigurationError
from .errors import TokenRefreshError
from .errors import UpstreamRequestError
from .models import CallbackResolution
from .models import CommandResult
from .models import DedupeEntry
from .models import DeviceCache
from .models import DiscoveredDevice
from .models import InternalApiResolution
from .models import PendingOAuthState
from .models import PersistentState
from .models import RawCommandRequest
from .models import RecentError
from .models import StartWarmingRequest
from .models import TokenBundle
from .oauth import OAuthManager
from .settings import ServiceSettings
from .smartthings_client import SmartThingsClient
from .storage import StateStorage


StateMutator = Callable[[PersistentState], None]


class RuntimeStateStore:
    def __init__(
        self,
        storage: StateStorage,
        recent_errors_limit: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._storage = storage
        self._recent_errors_limit = recent_errors_limit
        self._logger = logger or logging.getLogger(__name__)
        self._state = PersistentState()
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        self._state = self._storage.load()

    async def snapshot(self) -> PersistentState:
        async with self._lock:
            return self._state.model_copy(deep=True)

    async def set_pending_oauth(self, pending_state: PendingOAuthState) -> None:
        await self._update(lambda state: state.__setattr__("pending_oauth_state", pending_state))

    async def clear_pending_oauth(self) -> None:
        await self._update(lambda state: state.__setattr__("pending_oauth_state", None))

    async def set_token(self, token: TokenBundle) -> None:
        def apply(state: PersistentState) -> None:
            state.token = token
            state.auth_broken = False
            state.auth_broken_reason = None

        await self._update(apply)

    async def mark_auth_broken(self, reason: str) -> None:
        def apply(state: PersistentState) -> None:
            state.auth_broken = True
            state.auth_broken_reason = reason

        await self._update(apply)

    async def mark_contact_success(self) -> None:
        await self._update(lambda state: state.__setattr__("last_successful_contact_at", datetime.now(UTC)))

    async def update_device_cache(
        self,
        metadata: dict[str, Any] | None,
        status: dict[str, Any] | None,
    ) -> None:
        def apply(state: PersistentState) -> None:
            state.device_cache = DeviceCache(
                metadata=metadata,
                status=status,
                last_refreshed_at=datetime.now(UTC),
            )

        await self._update(apply)

    async def update_discovered_devices(self, devices: list[DiscoveredDevice]) -> None:
        await self._update(
            lambda state: state.__setattr__("discovered_devices", devices),
        )

    async def record_error(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        error = RecentError(
            created_at=datetime.now(UTC),
            code=code,
            message=message,
            details=details,
        )

        def apply(state: PersistentState) -> None:
            state.recent_errors.append(error)
            state.recent_errors = state.recent_errors[-self._recent_errors_limit :]

        await self._update(apply)
        self._logger.warning("event=recent_error code=%s message=%s", code, message)

    async def is_duplicate_start_warming(self, key: str) -> bool:
        snapshot = await self.snapshot()
        dedupe = snapshot.start_warming_dedupe
        return bool(dedupe and dedupe.key == key and dedupe.expires_at > datetime.now(UTC))

    async def remember_start_warming(self, key: str, ttl_seconds: int) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        await self._update(
            lambda state: state.__setattr__(
                "start_warming_dedupe",
                DedupeEntry(key=key, expires_at=expires_at),
            )
        )

    async def _update(self, mutator: StateMutator) -> None:
        async with self._lock:
            working = self._state.model_copy(deep=True)
            mutator(working)
            self._storage.save(working)
            self._state = working


class BridgeService:
    def __init__(
        self,
        settings: ServiceSettings,
        storage: StateStorage | None = None,
        http_client: httpx.AsyncClient | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self._storage = storage or StateStorage(settings.state_path)
        self._state_store = RuntimeStateStore(
            storage=self._storage,
            recent_errors_limit=settings.recent_errors_limit,
            logger=self.logger,
        )
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._oauth: OAuthManager | None = None
        self._smartthings: SmartThingsClient | None = None
        self._refresh_lock = asyncio.Lock()

    async def startup(self) -> None:
        await self._state_store.load()
        if self._http_client is None:
            timeout = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=20.0)
            self._http_client = httpx.AsyncClient(timeout=timeout)
        self._oauth = OAuthManager(self.settings, self._http_client)
        self._smartthings = SmartThingsClient(
            settings=self.settings,
            http_client=self._http_client,
            access_token_provider=self._get_access_token,
            mark_contact_success=self._state_store.mark_contact_success,
            mark_auth_broken=self._mark_auth_broken,
            logger=self.logger,
        )

    async def shutdown(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()

    async def get_status_payload(
        self,
        request: Request | None = None,
    ) -> dict[str, Any]:
        state = await self._state_store.snapshot()
        callback = await self.resolve_callback_url(request)
        internal_api = await self.resolve_internal_api()
        expires_in = None
        expired = None
        if state.token is not None:
            expires_in = int((state.token.expires_at - datetime.now(UTC)).total_seconds())
            expired = expires_in <= 0

        return {
            "oauth_configured": self.settings.has_oauth_credentials(),
            "device_id_configured": self.settings.has_device_id(),
            "configured": self.settings.is_configured(),
            "auth_state": self._auth_state(state),
            "reauth_required": state.auth_broken,
            "auth_broken_reason": state.auth_broken_reason,
            "pending_oauth": state.pending_oauth_state is not None,
            "token_present": state.token is not None,
            "token_expires_at": state.token.expires_at if state.token else None,
            "token_expires_in_seconds": expires_in,
            "token_expired": expired,
            "device_id": self.settings.smartthings_device_id,
            "last_successful_contact_at": state.last_successful_contact_at,
            "device_cache": sanitize_for_display(state.device_cache.model_dump(mode="json")),
            "discovered_devices": sanitize_for_display([device.model_dump(mode="json") for device in state.discovered_devices]),
            "recent_errors": sanitize_for_display([error.model_dump(mode="json") for error in state.recent_errors]),
            "oauth_callback": callback.model_dump(),
            "internal_api": internal_api.model_dump(),
        }

    async def get_cached_device_payload(self) -> dict[str, Any]:
        state = await self._state_store.snapshot()
        return sanitize_for_display(state.device_cache.model_dump(mode="json"))

    async def get_cached_discovered_devices(self) -> list[dict[str, Any]]:
        state = await self._state_store.snapshot()
        return sanitize_for_display([device.model_dump(mode="json") for device in state.discovered_devices])

    async def refresh_device_payload(self) -> dict[str, Any]:
        device, status = await self.refresh_device_info()
        return sanitize_for_display({"metadata": device, "status": status})

    async def refresh_discovered_devices(self) -> list[dict[str, Any]]:
        self._require_oauth_configured()
        devices = await self._smartthings_client.list_devices()
        summaries = [_summarize_device(device) for device in devices]
        summaries.sort(
            key=lambda device: (
                not device.looks_like_oven,
                (device.label or device.name or device.device_id).lower(),
            )
        )
        await self._state_store.update_discovered_devices(summaries)
        return sanitize_for_display([device.model_dump(mode="json") for device in summaries])

    async def start_oauth_flow(self, request: Request) -> str:
        self._require_oauth_configured()
        callback = await self.resolve_callback_url(request)
        if not callback.ready or not callback.callback_url:
            raise ConfigurationError(
                "OAuth callback URL is not ready.",
                details=callback.model_dump(),
            )
        oauth = self._oauth_client
        pending = oauth.create_pending_state(callback.callback_url)
        await self._state_store.set_pending_oauth(pending)
        return oauth.build_authorization_url(pending)

    async def complete_oauth_flow(self, code: str, supplied_state: str) -> None:
        oauth = self._oauth_client
        snapshot = await self._state_store.snapshot()
        oauth.validate_state(snapshot.pending_oauth_state, supplied_state)
        pending = snapshot.pending_oauth_state
        assert pending is not None

        token = await oauth.exchange_code(code, pending.callback_url)
        await self._state_store.set_token(token)
        await self._state_store.clear_pending_oauth()

    async def refresh_device_info(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self._require_device_configured()
        smartthings = self._smartthings_client
        device, status = await asyncio.gather(
            smartthings.get_device(),
            smartthings.get_device_status(),
        )
        await self._state_store.update_device_cache(device, status)
        return device, status

    async def stop_oven(self) -> CommandResult:
        device, status = await self.refresh_device_info()
        smartthings = self._smartthings_client
        if smartthings.is_likely_stopped(status):
            return CommandResult(
                action="stop",
                result="already_stopped",
                device_status_checked=True,
            )

        commands = smartthings.build_stop_commands(device, status)
        await smartthings.send_device_commands(commands)
        return CommandResult(
            action="stop",
            result="command_sent",
            commands=commands,
            device_status_checked=True,
        )

    async def start_warming(self, request: StartWarmingRequest) -> CommandResult:
        dedupe_key = self._dedupe_key(request)
        if await self._state_store.is_duplicate_start_warming(dedupe_key):
            return CommandResult(
                action="start_warming",
                result="suppressed_duplicate",
                deduplicated=True,
            )

        device, status = await self.refresh_device_info()
        smartthings = self._smartthings_client
        commands, duration_applied = smartthings.build_start_warming_commands(
            request,
            device,
            status,
        )
        await smartthings.send_device_commands(commands)
        await self._state_store.remember_start_warming(dedupe_key, self.settings.start_warming_dedupe_seconds)
        return CommandResult(
            action="start_warming",
            result="command_sent",
            commands=commands,
            duration_applied=duration_applied,
            device_status_checked=True,
        )

    async def send_raw_commands(self, request: RawCommandRequest) -> CommandResult:
        self._require_device_configured()
        await self._smartthings_client.send_device_commands(request.commands)
        return CommandResult(
            action="raw_command",
            result="command_sent",
            commands=request.commands,
        )

    async def resolve_callback_url(self, request: Request | None) -> CallbackResolution:
        if request is not None:
            from_request = self._callback_from_request(request)
            if from_request is not None:
                return from_request

        return await self._callback_from_supervisor()

    async def resolve_internal_api(self) -> InternalApiResolution:
        if not self.settings.supervisor_token:
            return InternalApiResolution(
                ready=False,
                reason=("SUPERVISOR_TOKEN is not available, so the add-on hostname cannot be discovered."),
                source="supervisor",
            )

        try:
            addon_info = await self._supervisor_request("/addons/self/info")
        except BridgeError as err:
            return InternalApiResolution(
                ready=False,
                reason=err.message,
                source="supervisor",
            )

        addon_data = addon_info.get("data", {})
        hostname = addon_data.get("hostname") if isinstance(addon_data, dict) else None
        if not isinstance(hostname, str) or not hostname:
            return InternalApiResolution(
                ready=False,
                reason="The Supervisor did not return an internal hostname for this add-on.",
                source="supervisor",
            )

        return InternalApiResolution(
            ready=True,
            base_url=f"http://{hostname}:{self.settings.api_port}",
            hostname=hostname,
            source="supervisor",
        )

    async def record_exception(self, err: BridgeError) -> None:
        await self._state_store.record_error(
            err.code,
            err.message,
            sanitize_details(err.details),
        )

    async def _get_access_token(self, force_refresh: bool) -> str:
        self._require_oauth_configured()
        snapshot = await self._state_store.snapshot()
        if snapshot.auth_broken:
            raise AuthenticationRequiredError("SmartThings authorization is marked as broken and needs reauthentication.")
        if snapshot.token is None:
            raise AuthenticationRequiredError

        if not force_refresh and snapshot.token.expires_at > self._refresh_deadline:
            return snapshot.token.access_token

        return await self._refresh_access_token(force_refresh=force_refresh)

    async def _refresh_access_token(self, *, force_refresh: bool) -> str:
        async with self._refresh_lock:
            current = await self._state_store.snapshot()
            if current.token is None:
                raise AuthenticationRequiredError
            if not force_refresh and current.token.expires_at > self._refresh_deadline and not current.auth_broken:
                return current.token.access_token

            try:
                refreshed = await self._oauth_client.refresh_tokens(current.token.refresh_token)
            except TokenRefreshError:
                await self._mark_auth_broken("token_refresh_failed")
                raise

            await self._state_store.set_token(
                TokenBundle(
                    access_token=refreshed.access_token,
                    refresh_token=refreshed.refresh_token or current.token.refresh_token,
                    expires_at=refreshed.expires_at,
                    scope=refreshed.scope,
                    token_type=refreshed.token_type,
                )
            )
            latest = await self._state_store.snapshot()
            assert latest.token is not None
            return latest.token.access_token

    async def _mark_auth_broken(self, reason: str) -> None:
        await self._state_store.mark_auth_broken(reason)

    def _callback_from_request(self, request: Request) -> CallbackResolution | None:
        ingress_path = request.headers.get("x-ingress-path")
        if not ingress_path:
            return None

        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if not host:
            return CallbackResolution(
                ready=False,
                reason="Unable to determine the Home Assistant host for ingress.",
                source="request",
            )
        if scheme != "https":
            return CallbackResolution(
                ready=False,
                reason="Home Assistant ingress must be reached over HTTPS for SmartThings OAuth.",
                source="request",
            )

        ingress_path = ingress_path.rstrip("/")
        callback_url = f"{scheme}://{host}{ingress_path}/oauth/callback"
        return CallbackResolution(
            ready=True,
            callback_url=callback_url,
            source="request",
        )

    async def _callback_from_supervisor(self) -> CallbackResolution:
        if not self.settings.supervisor_token:
            return CallbackResolution(
                ready=False,
                reason=("SUPERVISOR_TOKEN is not available, so callback discovery cannot query Home Assistant."),
                source="supervisor",
            )

        try:
            core_config = await self._supervisor_core_request("/config")
            addon_info = await self._supervisor_request("/addons/self/info")
        except BridgeError as err:
            return CallbackResolution(
                ready=False,
                reason=err.message,
                source="supervisor",
            )

        external_url = core_config.get("external_url")
        addon_data = addon_info.get("data", {})
        ingress_url = addon_data.get("ingress_url") if isinstance(addon_data, dict) else None
        if not isinstance(external_url, str) or not external_url:
            return CallbackResolution(
                ready=False,
                reason="Home Assistant external_url is not configured.",
                source="supervisor",
            )
        if not external_url.startswith("https://"):
            return CallbackResolution(
                ready=False,
                reason="Home Assistant external_url must use HTTPS for SmartThings OAuth.",
                source="supervisor",
            )
        if not isinstance(ingress_url, str) or not ingress_url:
            return CallbackResolution(
                ready=False,
                reason="The Supervisor did not return an ingress URL for this add-on yet.",
                source="supervisor",
            )

        if ingress_url.startswith(("http://", "https://")):
            base_url = ingress_url.rstrip("/")
        else:
            base_url = urljoin(external_url.rstrip("/") + "/", ingress_url.lstrip("/")).rstrip("/")

        return CallbackResolution(
            ready=True,
            callback_url=f"{base_url}/oauth/callback",
            source="supervisor",
        )

    async def _supervisor_core_request(self, path: str) -> dict[str, Any]:
        return await self._supervisor_request(
            f"/core/api{path}",
            unwrap_data=False,
        )

    async def _supervisor_request(
        self,
        path: str,
        unwrap_data: bool | None = None,
    ) -> dict[str, Any]:
        assert self._http_client is not None
        should_unwrap_data = True if unwrap_data is None else unwrap_data
        headers = {"Authorization": f"Bearer {self.settings.supervisor_token}"}
        try:
            response = await self._http_client.get(
                f"{self.settings.supervisor_url}{path}",
                headers=headers,
            )
        except httpx.TimeoutException as err:
            raise UpstreamRequestError("Timed out while contacting the Home Assistant Supervisor.") from err
        except httpx.HTTPError as err:
            raise UpstreamRequestError(
                "Unable to reach the Home Assistant Supervisor.",
                details={"error": str(err), "path": path},
            ) from err

        if response.status_code >= 400:
            raise UpstreamRequestError(
                "Supervisor request failed.",
                details={"status_code": response.status_code, "path": path},
            )

        try:
            payload = response.json()
        except ValueError as err:
            raise UpstreamRequestError("Supervisor returned invalid JSON.") from err

        if should_unwrap_data:
            if isinstance(payload, dict) and payload.get("data") is not None:
                return payload
            raise UpstreamRequestError(
                "Supervisor response did not contain expected data.",
                details={"path": path},
            )
        if isinstance(payload, dict):
            return payload
        raise UpstreamRequestError("Supervisor response body was not an object.")

    def _require_oauth_configured(self) -> None:
        if not self.settings.smartthings_client_id:
            raise ConfigurationError("smartthings_client_id is required.")
        if self.settings.smartthings_client_secret is None:
            raise ConfigurationError("smartthings_client_secret is required.")

    def _require_device_configured(self) -> None:
        self._require_oauth_configured()
        if not self.settings.smartthings_device_id:
            raise ConfigurationError("smartthings_device_id is required before refreshing or controlling a device.")

    def _auth_state(self, state: PersistentState) -> str:
        if not self.settings.has_oauth_credentials():
            return "not_configured"
        if state.auth_broken:
            return "reauth_required"
        if state.token is None:
            return "needs_authorization"
        return "authorized"

    def _dedupe_key(self, request: StartWarmingRequest) -> str:
        payload = json.dumps(request.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def _refresh_deadline(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.settings.token_refresh_skew_seconds)

    @property
    def _oauth_client(self) -> OAuthManager:
        if self._oauth is None:
            raise RuntimeError("Service has not been started.")
        return self._oauth

    @property
    def _smartthings_client(self) -> SmartThingsClient:
        if self._smartthings is None:
            raise RuntimeError("Service has not been started.")
        return self._smartthings


def sanitize_for_display(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if any(token in key.lower() for token in ("token", "secret", "authorization")):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = sanitize_for_display(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_display(item) for item in value]
    return value


def sanitize_details(details: object) -> dict[str, Any] | None:
    if details is None:
        return None
    sanitized = sanitize_for_display(details)
    if isinstance(sanitized, dict):
        return sanitized
    return {"value": sanitized}


def _summarize_device(device: dict[str, Any]) -> DiscoveredDevice:
    capabilities = sorted(_device_capabilities(device))
    device_id = _device_label(device, "deviceId") or "<missing-device-id>"
    return DiscoveredDevice(
        device_id=device_id,
        label=_device_label(device, "label"),
        name=_device_label(device, "name"),
        manufacturer_name=_device_label(device, "manufacturerName"),
        device_type_name=_device_label(device, "type"),
        location_id=_device_label(device, "locationId"),
        room_id=_device_label(device, "roomId"),
        capabilities=capabilities,
        looks_like_oven=_looks_like_oven(device, capabilities),
    )


def _device_label(device: dict[str, Any], key: str) -> str | None:
    value = device.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _device_capabilities(device: dict[str, Any]) -> set[str]:
    discovered: set[str] = set()
    components = device.get("components", [])
    if not isinstance(components, list):
        return discovered

    for component in components:
        if not isinstance(component, dict) or component.get("id") != "main":
            continue
        capability_list = component.get("capabilities", [])
        if not isinstance(capability_list, list):
            continue
        for capability in capability_list:
            if isinstance(capability, str):
                discovered.add(capability)
                continue
            if isinstance(capability, dict):
                identifier = capability.get("id")
                if isinstance(identifier, str) and identifier:
                    discovered.add(identifier)
    return discovered


def _looks_like_oven(device: dict[str, Any], capabilities: list[str]) -> bool:
    probe_values = [
        _device_label(device, "label"),
        _device_label(device, "name"),
        _device_label(device, "manufacturerName"),
        _device_label(device, "type"),
        " ".join(capabilities),
    ]
    haystack = " ".join(value for value in probe_values if value).lower()
    return any(token in haystack for token in ("oven", "range", "cook", "warming"))
