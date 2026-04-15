from __future__ import annotations

from custom_components.advanced_smartthings.const import (
    DEFAULT_SCAN_INTERVAL,
    DOOR_SENSOR_SCAN_INTERVAL,
)
from custom_components.advanced_smartthings.coordinator import coordinator_scan_interval
from custom_components.advanced_smartthings.discovery import build_device_catalog, parse_devices

from .conftest import (
    COOKTOP_DEVICE,
    FRIDGE_DEVICE,
    OVEN_DEVICE,
    OVEN_SETPOINT_DEFINITION,
    SAMSUNG_OVEN_MODE_DEFINITION,
    THERMOSTAT_COOLING_SETPOINT_DEFINITION,
)


def test_coordinator_scan_interval_prefers_fast_polling_for_fridge_doors() -> None:
    catalog = build_device_catalog(
        parse_devices([FRIDGE_DEVICE]),
        capability_definitions={
            ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
        },
    )

    assert coordinator_scan_interval(catalog) == DOOR_SENSOR_SCAN_INTERVAL


def test_coordinator_scan_interval_uses_default_without_door_sensors() -> None:
    catalog = build_device_catalog(
        parse_devices([OVEN_DEVICE, COOKTOP_DEVICE]),
        capability_definitions={
            ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
            ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
        },
    )

    assert coordinator_scan_interval(catalog) == DEFAULT_SCAN_INTERVAL
