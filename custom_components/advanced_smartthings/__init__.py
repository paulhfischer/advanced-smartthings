from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .api import async_build_api_client
from .capability_registry import (
    AdvancedSmartThingsBinarySensorEntityDescription,
    AdvancedSmartThingsNumberEntityDescription,
    AdvancedSmartThingsSelectEntityDescription,
    AdvancedSmartThingsSensorEntityDescription,
    AdvancedSmartThingsSwitchEntityDescription,
)
from .const import CONF_SELECTED_DEVICE_IDS, PLATFORMS
from .coordinator import AdvancedSmartThingsCoordinator, AdvancedSmartThingsRuntimeData
from .discovery import build_device_catalog, parse_devices
from .exceptions import SmartThingsApiError, SmartThingsConnectionError


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Advanced SmartThings from a config entry."""
    api = await async_build_api_client(hass, entry)

    try:
        device_records = parse_devices(await api.async_get_devices())
    except ConfigEntryAuthFailed:
        raise
    except SmartThingsConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except SmartThingsApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    selected_device_ids = set(entry.options.get(CONF_SELECTED_DEVICE_IDS, []))
    selected_records = [
        device for device in device_records if device.device_id in selected_device_ids
    ]
    if not selected_records:
        raise ConfigEntryNotReady("No SmartThings devices are selected for this config entry.")

    referenced_capabilities = {
        (capability.capability_id, capability.capability_version)
        for device in selected_records
        for capability in device.capabilities
    }
    capability_definitions = await api.async_prefetch_capability_definitions(
        referenced_capabilities
    )
    devices = build_device_catalog(selected_records, capability_definitions)
    if not any(device.supported_entities for device in devices.values()):
        raise ConfigEntryNotReady(
            "The selected SmartThings devices do not expose any supported capabilities."
        )

    coordinator = AdvancedSmartThingsCoordinator(hass, api=api, devices=devices, entry=entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = AdvancedSmartThingsRuntimeData(
        api=api,
        coordinator=coordinator,
        devices=devices,
    )
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_migrate_entity_ids(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Advanced SmartThings config entry."""
    await entry.runtime_data.coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename existing entity registry entries to stable English object IDs."""
    registry = er.async_get(hass)
    desired_entity_ids: dict[str, str] = {}

    for device in entry.runtime_data.devices.values():
        device_slug = slugify(device.label)
        for description in device.supported_entities:
            object_id_suffix = getattr(description, "object_id_suffix", None)
            if not object_id_suffix:
                continue
            platform = _platform_for_description(description)
            desired_entity_ids[f"{device.device_id}_{description.key}"] = (
                f"{platform}.{device_slug}_{object_id_suffix}"
            )

    for existing_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        desired_entity_id = desired_entity_ids.get(existing_entry.unique_id)
        if desired_entity_id is None or desired_entity_id == existing_entry.entity_id:
            continue
        try:
            registry.async_update_entity(
                existing_entry.entity_id,
                new_entity_id=desired_entity_id,
            )
        except ValueError:
            continue


def _platform_for_description(description) -> str:
    if isinstance(description, AdvancedSmartThingsSensorEntityDescription):
        return "sensor"
    if isinstance(description, AdvancedSmartThingsBinarySensorEntityDescription):
        return "binary_sensor"
    if isinstance(description, AdvancedSmartThingsSwitchEntityDescription):
        return "switch"
    if isinstance(description, AdvancedSmartThingsNumberEntityDescription):
        return "number"
    if isinstance(description, AdvancedSmartThingsSelectEntityDescription):
        return "select"
    raise ValueError(f"Unsupported description type for entity migration: {type(description)!r}")
