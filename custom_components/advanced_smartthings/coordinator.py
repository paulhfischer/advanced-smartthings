from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SmartThingsApiClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOOR_SENSOR_SCAN_INTERVAL,
    POST_COMMAND_REFRESH_DELAYS,
)
from .discovery import DiscoveredDevice
from .exceptions import SmartThingsApiError, SmartThingsConnectionError


@dataclass(slots=True)
class AdvancedSmartThingsRuntimeData:
    api: SmartThingsApiClient
    coordinator: AdvancedSmartThingsCoordinator
    devices: dict[str, DiscoveredDevice]


class AdvancedSmartThingsCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll SmartThings device status for the selected devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        api: SmartThingsApiClient,
        devices: dict[str, DiscoveredDevice],
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name="Advanced SmartThings",
            update_interval=coordinator_scan_interval(devices),
        )
        self.api = api
        self.devices = devices
        self.config_entry = entry
        self._post_command_refresh_task: asyncio.Task[None] | None = None

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            results = await asyncio.gather(
                *(self.api.async_get_device_status(device_id) for device_id in self.devices),
                return_exceptions=True,
            )
        except ConfigEntryAuthFailed:
            raise
        except SmartThingsConnectionError as err:
            raise UpdateFailed(str(err)) from err

        data: dict[str, dict[str, Any]] = {}
        for device_id, result in zip(self.devices, results, strict=False):
            if isinstance(result, ConfigEntryAuthFailed):
                raise result
            if isinstance(result, SmartThingsConnectionError | SmartThingsApiError):
                raise UpdateFailed(str(result)) from result
            if isinstance(result, Exception):
                raise UpdateFailed(str(result)) from result
            data[device_id] = result
        return data

    def async_schedule_post_command_refresh(self) -> None:
        """Schedule a short burst of refreshes after a command."""
        if self._post_command_refresh_task and not self._post_command_refresh_task.done():
            self._post_command_refresh_task.cancel()
        self._post_command_refresh_task = self.hass.async_create_task(
            self._async_post_command_refresh_burst()
        )

    async def async_shutdown(self) -> None:
        """Cancel outstanding background refresh work."""
        if self._post_command_refresh_task and not self._post_command_refresh_task.done():
            self._post_command_refresh_task.cancel()
            try:
                await self._post_command_refresh_task
            except asyncio.CancelledError:
                pass

    async def _async_post_command_refresh_burst(self) -> None:
        try:
            for delay in POST_COMMAND_REFRESH_DELAYS:
                await asyncio.sleep(delay)
                await self.async_request_refresh()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive logging around background tasks
            self.logger.debug("Post-command SmartThings refresh burst failed", exc_info=True)


def coordinator_scan_interval(devices: dict[str, DiscoveredDevice]):
    """Pick a polling interval based on the selected entity mix."""
    for device in devices.values():
        for entity in device.supported_entities:
            if getattr(entity, "translation_key", None) in {
                "refrigerator_door",
                "freezer_door",
            }:
                return DOOR_SENSOR_SCAN_INTERVAL
    return DEFAULT_SCAN_INTERVAL
