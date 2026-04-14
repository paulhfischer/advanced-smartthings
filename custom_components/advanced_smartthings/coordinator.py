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
from .const import DEFAULT_SCAN_INTERVAL
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
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self.devices = devices
        self.config_entry = entry

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
